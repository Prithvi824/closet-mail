"""ContactService: idempotent creation, tokens, resolution, blocking and KV sync."""

# 3rd party imports
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import NotFound
from mailalias.config import get_settings
from mailalias.mail.addresses import TOKEN_RE
from mailalias.models import Alias, User
from mailalias.services import kv_sync
from mailalias.services.aliases import AliasService
from mailalias.services.contacts import ContactService
from mailalias.services.users import UserService
from tests.fakes import FakeKv


async def _alias(session: AsyncSession, username: str) -> tuple[User, Alias]:
    """Create a committed user with one alias.

    Args:
        session: Test session.
        username: Username.
    Returns:
        (user, alias).
    """
    user = await UserService(session).create_user(
        username, f"{username}@example.com", "correct horse battery"
    )
    alias = await AliasService(session, get_settings()).create(user)
    await session.commit()
    return user, alias


async def test_get_or_create_is_idempotent(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Same sender (any case) maps to one contact; the token is synced once."""
    _, alias = await _alias(session, "hana")
    service = ContactService(session)
    first = await service.get_or_create(alias, "Alice@Example.org", "Alice")
    await session.commit()
    second = await service.get_or_create(alias, " alice@example.org ", "Alice A.")
    await session.commit()
    assert first.id == second.id
    assert second.sender_name == "Alice A."
    assert service.real_address(second) == "alice@example.org"
    assert TOKEN_RE.fullmatch(first.token)
    contact_syncs = [call for call in dispatched if call[0] == "kv.sync_contact"]
    assert contact_syncs == [("kv.sync_contact", str(first.id))]


async def test_tokens_unique_per_alias_and_sender(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Different senders, or the same sender on another alias, get distinct tokens."""
    user, alias = await _alias(session, "ivan")
    other = await AliasService(session, get_settings()).create(user)
    service = ContactService(session)
    tokens = {
        (await service.get_or_create(alias, "a@example.org", None)).token,
        (await service.get_or_create(alias, "b@example.org", None)).token,
        (await service.get_or_create(other, "a@example.org", None)).token,
    }
    assert len(tokens) == 3


async def test_token_collision_retries(
    session: AsyncSession, dispatched: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A colliding token is retried with a fresh one."""
    _, alias = await _alias(session, "jade")
    service = ContactService(session)
    taken = await service.get_or_create(alias, "a@example.org", None)
    tokens = iter([taken.token, "bbbbbbbbbbbbbbbb"])
    monkeypatch.setattr("mailalias.services.contacts.new_reply_token", lambda: next(tokens))
    fresh = await service.get_or_create(alias, "b@example.org", None)
    assert fresh.token == "bbbbbbbbbbbbbbbb"


async def test_resolve_token(session: AsyncSession, dispatched: list[tuple[str, str]]) -> None:
    """Known tokens resolve (case-insensitive); malformed or unknown ones do not."""
    _, alias = await _alias(session, "kira")
    service = ContactService(session)
    contact = await service.get_or_create(alias, "a@example.org", None)
    assert (await service.resolve_token(contact.token.upper())) == contact
    assert await service.resolve_token("short") is None
    assert await service.resolve_token("aaaaaaaaaaaaaaaa") is None


async def test_set_blocked_enforces_ownership(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Only the alias owner can block a contact."""
    owner, alias = await _alias(session, "lena")
    stranger, _ = await _alias(session, "milo")
    service = ContactService(session)
    contact = await service.get_or_create(alias, "a@example.org", None)
    assert (await service.set_blocked(contact.id, owner.id, True)).blocked
    with pytest.raises(NotFound):
        await service.set_blocked(contact.id, stranger.id, False)


async def test_sync_contact_writes_token(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """The KV task body writes r:<token> = V."""
    _, alias = await _alias(session, "nora")
    contact = await ContactService(session).get_or_create(alias, "a@example.org", None)
    kv = FakeKv()
    await kv_sync.sync_contact(session, kv, contact.id)  # type: ignore[arg-type]
    assert kv.data == {f"r:{contact.token}": "V"}
