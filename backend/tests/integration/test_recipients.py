"""Recipient management: duplicates, verification links, last-recipient guard, PGP keys."""

# 1st party imports
import re

# 3rd party imports
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.outbound import FakeMailer
from mailalias.services.users import UserService
from tests.pgp_keys import PgpTestKey, make_key

pytestmark = pytest.mark.usefixtures("relaxed_rate_limits")
PASSWORD = "correct horse battery"


@pytest.fixture(scope="session")
def keys() -> dict[str, PgpTestKey]:
    """Good, sign-only and already-expired test keys (generated once).

    Returns:
        Keys by name.
    """
    return {
        "good": make_key("good@example.com"),
        "sign_only": make_key("sign@example.com", encrypt=False),
        "expired": make_key("old@example.com", expire="1d", faked_time="20200101T000000"),
    }


@pytest.fixture
async def signed_in(client: httpx.AsyncClient, session: AsyncSession) -> httpx.AsyncClient:
    """A logged-in regular user "erin" with one verified recipient.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        The same client, now authenticated.
    """
    await UserService(session).create_user("erin", "erin@example.com", PASSWORD)
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "erin", "password": PASSWORD})
    assert login.status_code == 200
    return client


def _verify_path(mailer: FakeMailer) -> str:
    """Extract the verification path from the last email.

    Args:
        mailer: Fake mailer.
    Returns:
        The /api/v1/recipients/verify/<token> path.
    """
    match = re.search(
        r"(/api/v1/recipients/verify/[A-Za-z0-9_-]+)", mailer.sent[-1].message.get_content()
    )
    assert match
    return match.group(1)


async def test_add_duplicate_and_verify(signed_in: httpx.AsyncClient, mailer: FakeMailer) -> None:
    """Adding twice conflicts; GET shows a page without verifying; POST verifies once.

    Args:
        signed_in: Authenticated client.
        mailer: Fake mailer.
    Returns:
        None.
    """
    created = await signed_in.post("/api/v1/recipients", json={"email": "Work@Example.org"})
    assert created.status_code == 201
    assert created.json()["verified"] is False
    duplicate = await signed_in.post("/api/v1/recipients", json={"email": "work@example.org"})
    assert duplicate.status_code == 409

    path = _verify_path(mailer)
    page = await signed_in.get(path)
    assert page.status_code == 200 and "<form" in page.text
    listed = (await signed_in.get("/api/v1/recipients")).json()
    assert [r["verified"] for r in listed if r["email"] == "work@example.org"] == [False]

    # The confirmation form posts without the CSRF header, like a browser form would.
    confirmed = await signed_in.post(path, headers={"X-Requested-With": ""})
    assert confirmed.status_code == 200 and "confirmed" in confirmed.text
    again = await signed_in.post(path, headers={"X-Requested-With": ""})
    assert again.status_code == 404
    listed = (await signed_in.get("/api/v1/recipients")).json()
    assert [r["verified"] for r in listed if r["email"] == "work@example.org"] == [True]


async def test_cannot_remove_last_verified_recipient(signed_in: httpx.AsyncClient) -> None:
    """Deleting or disabling the only verified recipient is refused.

    Args:
        signed_in: Authenticated client.
    Returns:
        None.
    """
    only = (await signed_in.get("/api/v1/recipients")).json()[0]
    assert only["is_default"] is True
    assert (await signed_in.delete(f"/api/v1/recipients/{only['id']}")).status_code == 422
    disable = await signed_in.patch(f"/api/v1/recipients/{only['id']}", json={"disabled": True})
    assert disable.status_code == 422


async def test_other_users_recipients_are_hidden(
    signed_in: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Another user's recipient id behaves as not found.

    Args:
        signed_in: Authenticated client.
        session: Test session.
    Returns:
        None.
    """
    other = await UserService(session).create_user("frank", "frank@example.com", PASSWORD)
    await session.commit()
    response = await signed_in.delete(f"/api/v1/recipients/{other.default_recipient_id}")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("key_name", "message"),
    [("sign_only", "encryption"), ("expired", "expired"), ("private", "private")],
)
async def test_unusable_pgp_keys_rejected(
    signed_in: httpx.AsyncClient, keys: dict[str, PgpTestKey], key_name: str, message: str
) -> None:
    """Sign-only, expired and private keys are rejected with a clear message.

    Args:
        signed_in: Authenticated client.
        keys: Test keys.
        key_name: Which bad key to upload.
        message: Expected fragment of the error.
    Returns:
        None.
    """
    armored = keys["good"].private if key_name == "private" else keys[key_name].public
    recipient = (await signed_in.get("/api/v1/recipients")).json()[0]
    response = await signed_in.put(
        f"/api/v1/recipients/{recipient['id']}/pgp", json={"public_key": armored}
    )
    assert response.status_code == 422
    assert message in response.json()["error"]["message"].lower()


async def test_garbage_pgp_key_rejected(signed_in: httpx.AsyncClient) -> None:
    """Text that is not a key is rejected.

    Args:
        signed_in: Authenticated client.
    Returns:
        None.
    """
    recipient = (await signed_in.get("/api/v1/recipients")).json()[0]
    response = await signed_in.put(
        f"/api/v1/recipients/{recipient['id']}/pgp", json={"public_key": "not a key"}
    )
    assert response.status_code == 422


async def test_valid_pgp_key_set_and_cleared(
    signed_in: httpx.AsyncClient, keys: dict[str, PgpTestKey]
) -> None:
    """A good key stores its fingerprint; null clears it.

    Args:
        signed_in: Authenticated client.
        keys: Test keys.
    Returns:
        None.
    """
    recipient = (await signed_in.get("/api/v1/recipients")).json()[0]
    url = f"/api/v1/recipients/{recipient['id']}/pgp"
    response = await signed_in.put(
        url, json={"public_key": keys["good"].public, "protect_subject": True}
    )
    assert response.status_code == 200
    assert response.json()["pgp_fingerprint"] == keys["good"].fingerprint
    assert response.json()["pgp_protect_subject"] is True
    cleared = await signed_in.put(url, json={"public_key": None})
    assert cleared.json()["pgp_fingerprint"] is None


@pytest.mark.parametrize(
    "email", ["x@closetcompute.online", "t@rp.closetcompute.online", "a@Gina.ClosetCompute.online"]
)
async def test_service_addresses_rejected_as_recipients(
    signed_in: httpx.AsyncClient, email: str
) -> None:
    """Our own domains cannot be recipients (mail would loop)."""
    response = await signed_in.post("/api/v1/recipients", json={"email": email})
    assert response.status_code == 422
