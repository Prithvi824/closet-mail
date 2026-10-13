"""Aliases: generation, validation, state machine, bulk actions, limits and KV sync."""

# 1st party imports
import re
from datetime import UTC, datetime, timedelta

# 3rd party imports
import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.models import Alias, AliasState, User
from mailalias.services import kv_sync
from mailalias.services.aliases import AliasService
from mailalias.services.users import UserService
from tests.fakes import FakeKv

pytestmark = pytest.mark.usefixtures("relaxed_rate_limits")
PASSWORD = "correct horse battery"
API = "/api/v1/aliases"


async def _user(session: AsyncSession, username: str) -> User:
    """Create a committed user.

    Args:
        session: Test session.
        username: Username.
    Returns:
        The user.
    """
    user = await UserService(session).create_user(username, f"{username}@example.com", PASSWORD)
    await session.commit()
    return user


@pytest.fixture
async def gina(client: httpx.AsyncClient, session: AsyncSession) -> User:
    """User "gina", logged in on `client`.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        The user.
    """
    user = await _user(session, "gina")
    response = await client.post(
        "/api/v1/auth/login", json={"username": "gina", "password": PASSWORD}
    )
    assert response.status_code == 200
    return user


@pytest.mark.usefixtures("gina")
async def test_generated_formats(client: httpx.AsyncClient) -> None:
    """Word and character formats produce the documented shapes on the shared domain.

    Args:
        client: Authenticated client.
    Returns:
        None.
    """
    words = (await client.post(API, json={"format": "words"})).json()
    chars = (await client.post(API, json={"format": "chars"})).json()
    assert re.fullmatch(r"[a-z]+\.[a-z]+\d{2}@closetcompute\.online", words["address"])
    assert re.fullmatch(r"[a-z0-9]{10}@closetcompute\.online", chars["address"])
    assert words["state"] == "active" and words["kind"] == "shared"


@pytest.mark.usefixtures("gina")
async def test_custom_subdomain_alias(client: httpx.AsyncClient) -> None:
    """A subdomain alias lives on <username>.<domain>.

    Args:
        client: Authenticated client.
    Returns:
        None.
    """
    created = await client.post(API, json={"local_part": "Shop", "subdomain": True})
    assert created.status_code == 201
    assert created.json()["address"] == "shop@gina.closetcompute.online"


@pytest.mark.usefixtures("gina")
@pytest.mark.parametrize(
    ("local_part", "code"),
    [
        ("postmaster", "reserved_local_part"),
        ("abuse", "reserved_local_part"),
        ("bad..dots", "invalid_local_part"),
        (".leading", "invalid_local_part"),
        ("has space", "invalid_local_part"),
        ("trailing.", "invalid_local_part"),
    ],
)
async def test_invalid_or_reserved_local_parts(
    client: httpx.AsyncClient, local_part: str, code: str
) -> None:
    """Reserved and malformed names are rejected with specific codes.

    Args:
        client: Authenticated client.
        local_part: Requested name.
        code: Expected error code.
    Returns:
        None.
    """
    response = await client.post(API, json={"local_part": local_part})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


@pytest.mark.usefixtures("gina")
async def test_duplicate_custom_alias_conflicts(client: httpx.AsyncClient) -> None:
    """Taking an existing address returns 409.

    Args:
        client: Authenticated client.
    Returns:
        None.
    """
    assert (await client.post(API, json={"local_part": "news"})).status_code == 201
    second = await client.post(API, json={"local_part": "news"})
    assert second.status_code == 409 and second.json()["error"]["code"] == "alias_taken"


@pytest.mark.usefixtures("gina")
async def test_state_machine_and_forget(
    client: httpx.AsyncClient, session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """active -> inactive -> deleted -> restored(inactive) -> forgotten; KV marks follow.

    Args:
        client: Authenticated client.
        session: Test session.
        dispatched: Captured KV dispatches.
    Returns:
        None.
    """
    alias = (await client.post(API, json={"local_part": "flow"})).json()
    url = f"{API}/{alias['id']}"
    assert dispatched[-1] == ("kv.sync_alias", alias["id"])

    assert (await client.patch(url, json={"active": False})).json()["state"] == "inactive"
    deleted = (await client.delete(url)).json()
    assert deleted["state"] == "deleted" and deleted["deleted_at"]
    assert (await client.patch(url, json={"active": True})).status_code == 409
    listed = (await client.get(API)).json()
    assert alias["id"] not in [a["id"] for a in listed["items"]]
    assert (await client.get(API, params={"state": "deleted"})).json()["total"] == 1

    restored = await client.post(f"{url}/restore")
    assert restored.json()["state"] == "inactive"

    await client.delete(url)
    await session.execute(
        update(Alias)
        .where(Alias.address == alias["address"])
        .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )
    await session.commit()
    assert (await client.post(f"{url}/restore")).status_code == 409

    assert (await client.post(f"{url}/forget")).status_code == 204
    assert (await client.get(url)).status_code == 404
    again = await client.post(API, json={"local_part": "flow"})
    assert again.status_code == 409  # forgotten addresses stay reserved forever
    assert len([c for c in dispatched if c[1] == alias["id"]]) >= 5


async def test_bulk_limits_and_ownership(
    client: httpx.AsyncClient, session: AsyncSession, gina: User
) -> None:
    """Bulk works on own aliases, rejects >100 ids, and 404s on another user's alias.

    Args:
        client: Authenticated client.
        session: Test session.
        gina: The signed-in user.
    Returns:
        None.
    """
    ids = [(await client.post(API, json={})).json()["id"] for _ in range(3)]
    result = await client.post(f"{API}/bulk", json={"ids": ids, "action": "deactivate"})
    assert result.json() == {"changed": 3}

    too_many = await client.post(
        f"{API}/bulk",
        json={"ids": [ids[0]] * 101, "action": "delete"},
    )
    assert too_many.status_code == 422

    other = await _user(session, "hank")
    other_alias = await AliasService(session, get_settings()).create(other, local_part="hank1")
    await session.commit()
    mixed = await client.post(
        f"{API}/bulk", json={"ids": [ids[0], str(other_alias.id)], "action": "delete"}
    )
    assert mixed.status_code == 404
    assert (await client.get(f"{API}/{other_alias.id}")).status_code == 404


async def test_create_rate_limit(
    client: httpx.AsyncClient, session: AsyncSession, gina: User
) -> None:
    """Per-user alias creation limit returns 429 once exceeded.

    Args:
        client: Authenticated client.
        session: Test session.
        gina: The signed-in user.
    Returns:
        None.
    """
    gina.limits = {"alias_creates_per_hour": 2}
    await session.commit()
    codes = [(await client.post(API, json={})).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


@pytest.mark.usefixtures("gina")
async def test_search_and_labels(client: httpx.AsyncClient) -> None:
    """Search matches decrypted descriptions; label filter works.

    Args:
        client: Authenticated client.
    Returns:
        None.
    """
    label = (await client.post("/api/v1/labels", json={"name": "shopping"})).json()
    tagged = await client.post(
        API, json={"local_part": "store1", "description": "Bike Shop", "label_ids": [label["id"]]}
    )
    assert tagged.json()["label_ids"] == [label["id"]]
    await client.post(API, json={"local_part": "store2", "description": "Bank"})

    found = (await client.get(API, params={"q": "bike"})).json()
    assert [a["local_part"] for a in found["items"]] == ["store1"]
    by_label = (await client.get(API, params={"label": label["id"]})).json()
    assert by_label["total"] == 1
    duplicate = await client.post("/api/v1/labels", json={"name": "shopping"})
    assert duplicate.status_code == 409


async def test_subdomain_toggle_marks_kv(
    client: httpx.AsyncClient, gina: User, dispatched: list[tuple[str, str]]
) -> None:
    """Turning on the subdomain catch-all dispatches a subdomain sync.

    Args:
        client: Authenticated client.
        gina: The signed-in user.
        dispatched: Captured KV dispatches.
    Returns:
        None.
    """
    response = await client.patch("/api/v1/me/settings", json={"subdomain_catchall": True})
    assert response.status_code == 200
    assert ("kv.sync_subdomain", str(gina.id)) in dispatched


async def test_rollback_drops_pending_kv(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Marks made in a rolled-back transaction are never dispatched.

    Args:
        session: Test session.
        dispatched: Captured KV dispatches.
    Returns:
        None.
    """
    user = await _user(session, "ivan")
    dispatched.clear()
    await AliasService(session, get_settings()).create(user, local_part="gone")
    await session.rollback()
    assert dispatched == []


async def test_kv_sync_values_and_reconcile(session: AsyncSession) -> None:
    """sync writes A/I/D and r:/s: keys; reconcile repairs drift and only deletes in prod mode.

    Args:
        session: Test session.
    Returns:
        None.
    """
    user = await _user(session, "judy")
    service = AliasService(session, get_settings())
    active = await service.create(user, local_part="on")
    inactive = await service.create(user, local_part="off")
    inactive.state = AliasState.INACTIVE
    gone = await service.create(user, local_part="gone2")
    gone.state = AliasState.DELETED
    user.subdomain_catchall = True
    await session.commit()

    kv = FakeKv()
    for alias in (active, inactive, gone):
        await kv_sync.sync_alias(session, kv, alias.id)  # type: ignore[arg-type]
    await kv_sync.sync_subdomain(session, kv, user.id)  # type: ignore[arg-type]
    assert kv.data == {
        "a:on@closetcompute.online": "A",
        "a:off@closetcompute.online": "I",
        "a:gone2@closetcompute.online": "D",
        "s:judy": "C",
    }

    from mailalias.db import get_redis

    drifted = FakeKv({"a:stale@closetcompute.online": "A", "s:judy": "C"})
    summary = await kv_sync.reconcile(session, drifted, get_redis(), delete_extra=False)  # type: ignore[arg-type]
    assert summary["extra"] == 1 and "a:stale@closetcompute.online" in drifted.data
    assert drifted.data["a:on@closetcompute.online"] == "A"
    await kv_sync.reconcile(session, drifted, get_redis(), delete_extra=True)  # type: ignore[arg-type]
    assert "a:stale@closetcompute.online" not in drifted.data
