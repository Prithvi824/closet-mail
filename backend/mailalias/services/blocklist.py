"""Per-user blocklist: sender addresses or whole domains whose mail is never forwarded."""

# 1st party imports
import re
import uuid

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound, ValidationFailed
from mailalias.mail.addresses import normalize, split_address
from mailalias.models import BlockKind, BlocklistEntry, User
from mailalias.security.crypto import lookup_hash

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
LOCAL_RE = re.compile(r"^[^\s@<>()\[\],;:\"]{1,64}$")


def parse_pattern(pattern: str) -> tuple[str, BlockKind]:
    """Normalise a blocklist entry: "user@example.com" (address) or "example.com" / "@example.com".

    Args:
        pattern: User input.
    Returns:
        (normalised pattern, kind). Raises ValidationFailed.
    """
    value = normalize(pattern).removeprefix("@")
    if "@" in value:
        local, domain = split_address(value)
        if LOCAL_RE.match(local) and DOMAIN_RE.match(domain):
            return value, BlockKind.ADDRESS
    elif DOMAIN_RE.match(value):
        return value, BlockKind.DOMAIN
    raise ValidationFailed("Enter an email address or a domain such as example.com")


def candidate_hashes(address: str) -> list[str]:
    """Hashes that would block an address: itself, its domain and each parent domain.

    Args:
        address: Sender address (any case).
    Returns:
        Lookup hashes ("sub.example.com" is blocked by "example.com" as well).
    """
    address = normalize(address)
    if "@" not in address:
        return []
    labels = split_address(address)[1].split(".")
    domains = [".".join(labels[i:]) for i in range(len(labels) - 1)]
    return [lookup_hash(address), *(lookup_hash(domain) for domain in domains)]


class BlocklistService:
    """CRUD on a user's blocklist plus the forward-time lookup."""

    def __init__(self, db: AsyncSession) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
        Returns:
            None.
        """
        self.db = db

    async def list(self, user: User) -> list[BlocklistEntry]:
        """The user's entries, newest first.

        Args:
            user: Owner.
        Returns:
            Entries.
        """
        query = (
            select(BlocklistEntry)
            .where(BlocklistEntry.user_id == user.id)
            .order_by(BlocklistEntry.created_at.desc())
        )
        return list(await self.db.scalars(query))

    async def add(self, user: User, pattern: str) -> BlocklistEntry:
        """Block an address or domain.

        Args:
            user: Owner.
            pattern: Address or domain.
        Returns:
            The new entry. Raises ValidationFailed or Conflict (already blocked).
        """
        value, kind = parse_pattern(pattern)
        entry = BlocklistEntry(
            user_id=user.id, pattern=value, pattern_hash=lookup_hash(value), kind=kind
        )
        try:
            async with self.db.begin_nested():
                self.db.add(entry)
        except IntegrityError as exc:
            raise Conflict("Already blocked") from exc
        return entry

    async def delete(self, user: User, entry_id: uuid.UUID) -> None:
        """Remove an entry.

        Args:
            user: Owner.
            entry_id: Entry id.
        Returns:
            None. Raises NotFound.
        """
        entry = await self.db.get(BlocklistEntry, entry_id)
        if entry is None or entry.user_id != user.id:
            raise NotFound("Blocklist entry not found")
        await self.db.delete(entry)

    async def is_blocked(self, user_id: uuid.UUID, address: str) -> bool:
        """Whether mail from this sender is blocked for the user.

        Args:
            user_id: Owner id.
            address: Sender address.
        Returns:
            True if the address or one of its domains is listed.
        """
        hashes = candidate_hashes(address)
        if not hashes:
            return False
        query = select(BlocklistEntry.id).where(
            BlocklistEntry.user_id == user_id, BlocklistEntry.pattern_hash.in_(hashes)
        )
        return await self.db.scalar(query.limit(1)) is not None
