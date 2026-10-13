"""Alias lifecycle: generation, creation, updates, state transitions and bulk actions."""

# 1st party imports
import secrets
import string
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib import resources

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# local imports
from mailalias.api.errors import Conflict, NotFound, QuotaExceeded, ValidationFailed
from mailalias.config import Settings
from mailalias.mail.addresses import is_reserved_local_part, is_valid_local_part
from mailalias.models import (
    Alias,
    AliasFormat,
    AliasKind,
    AliasState,
    Label,
    Recipient,
    User,
    alias_labels,
)
from mailalias.services import kv_sync

GENERATE_ATTEMPTS = 5
RESTORE_WINDOW = timedelta(days=30)
BULK_LIMIT = 100
CHAR_ALPHABET = string.ascii_lowercase + string.digits
VISIBLE_STATES = (AliasState.ACTIVE, AliasState.INACTIVE)


@lru_cache
def wordlist() -> tuple[str, ...]:
    """Load the EFF short word list used for readable aliases.

    Returns:
        The words.
    """
    text = resources.files("mailalias.data").joinpath("wordlist.txt").read_text()
    return tuple(w for w in (line.strip() for line in text.splitlines()) if w and w[0] != "#")


def generate_local_part(alias_format: AliasFormat) -> str:
    """Generate a random local part.

    Args:
        alias_format: WORDS ("word.word42") or CHARS (10 random [a-z0-9]).
    Returns:
        The local part.
    """
    if alias_format == AliasFormat.CHARS:
        return "".join(secrets.choice(CHAR_ALPHABET) for _ in range(10))
    words = wordlist()
    return f"{secrets.choice(words)}.{secrets.choice(words)}{secrets.randbelow(100):02d}"


class AliasService:
    """Alias operations scoped to their owner."""

    def __init__(self, db: AsyncSession, settings: Settings, redis: Redis | None = None) -> None:
        """Build the service.

        Args:
            db: Database session.
            settings: Domains and default limits.
            redis: Needed for the per-hour creation limit.
        Returns:
            None.
        """
        self.db = db
        self.settings = settings
        self.redis = redis

    def _owned_query(self, user: User) -> Select[Alias]:
        """Base query for a user's aliases with recipients and labels loaded.

        Args:
            user: Owner.
        Returns:
            A select statement.
        """
        return (
            select(Alias)
            .where(Alias.user_id == user.id)
            .options(selectinload(Alias.recipients), selectinload(Alias.labels))
        )

    async def get_owned(self, user: User, alias_id: uuid.UUID) -> Alias:
        """Fetch one alias owned by the user.

        Args:
            user: Owner.
            alias_id: Alias id.
        Returns:
            The alias. Raises NotFound.
        """
        alias = await self.db.scalar(self._owned_query(user).where(Alias.id == alias_id))
        if alias is None:
            raise NotFound("Alias not found")
        return alias

    async def _check_create_rate(self, user: User) -> None:
        """Enforce the per-user aliases-per-hour limit.

        Args:
            user: Creator.
        Returns:
            None. Raises QuotaExceeded.
        """
        if self.redis is None:
            return
        limit = int(
            (user.limits or {}).get(
                "alias_creates_per_hour", self.settings.user_alias_creates_per_hour
            )
        )
        key = f"q:alias:{user.id}:{datetime.now(UTC):%Y%m%d%H}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 3700)
        if count > limit:
            raise QuotaExceeded(f"At most {limit} aliases can be created per hour")

    async def _owned_recipients(self, user: User, ids: Sequence[uuid.UUID]) -> list[Recipient]:
        """Resolve recipient ids that belong to the user and are verified.

        Args:
            user: Owner.
            ids: Requested recipient ids.
        Returns:
            Recipients. Raises ValidationFailed if any id is invalid.
        """
        if not ids:
            return []
        found = list(
            await self.db.scalars(
                select(Recipient).where(Recipient.id.in_(ids), Recipient.user_id == user.id)
            )
        )
        if len(found) != len(set(ids)) or any(r.verified_at is None for r in found):
            raise ValidationFailed("Recipients must be your own verified recipients")
        return found

    async def _owned_labels(self, user: User, ids: Sequence[uuid.UUID]) -> list[Label]:
        """Resolve label ids that belong to the user.

        Args:
            user: Owner.
            ids: Requested label ids.
        Returns:
            Labels. Raises ValidationFailed if any id is invalid.
        """
        if not ids:
            return []
        found = list(
            await self.db.scalars(select(Label).where(Label.id.in_(ids), Label.user_id == user.id))
        )
        if len(found) != len(set(ids)):
            raise ValidationFailed("Unknown label")
        return found

    def _domain_for(self, user: User, subdomain: bool) -> tuple[str, AliasKind]:
        """Pick the alias domain.

        Args:
            user: Owner.
            subdomain: Use the personal subdomain instead of the shared domain.
        Returns:
            (domain, kind).
        """
        if subdomain:
            return f"{user.username}.{self.settings.alias_domain}", AliasKind.SUBDOMAIN
        return self.settings.alias_domain, AliasKind.SHARED

    async def _insert(self, alias: Alias) -> bool:
        """Insert inside a savepoint so a duplicate address does not poison the transaction.

        Args:
            alias: New alias.
        Returns:
            True if inserted, False on address collision.
        """
        try:
            async with self.db.begin_nested():
                self.db.add(alias)
                await self.db.flush()
        except IntegrityError:
            return False
        return True

    async def create(
        self,
        user: User,
        *,
        alias_format: AliasFormat | None = None,
        local_part: str | None = None,
        subdomain: bool = False,
        description: str | None = None,
        recipient_ids: Sequence[uuid.UUID] = (),
        label_ids: Sequence[uuid.UUID] = (),
    ) -> Alias:
        """Create an alias, generated or custom.

        Args:
            user: Owner.
            alias_format: Generator for random aliases (defaults to the user's preference).
            local_part: Custom local part; generated when None.
            subdomain: Create on <username>.<alias domain>.
            description: Optional private note.
            recipient_ids: Recipients; empty means "the user's default recipient".
            label_ids: Labels to attach.
        Returns:
            The created alias. Raises ValidationFailed, Conflict or QuotaExceeded.
        """
        recipients = await self._owned_recipients(user, recipient_ids)
        labels = await self._owned_labels(user, label_ids)
        domain, kind = self._domain_for(user, subdomain)
        if local_part is not None:
            local_part = local_part.strip().lower()
            if not is_valid_local_part(local_part):
                raise ValidationFailed("Alias name is not allowed", code="invalid_local_part")
            if is_reserved_local_part(local_part):
                raise ValidationFailed("Alias name is reserved", code="reserved_local_part")
        await self._check_create_rate(user)

        attempts = 1 if local_part is not None else GENERATE_ATTEMPTS
        for _ in range(attempts):
            candidate = local_part or generate_local_part(alias_format or user.alias_format)
            alias = Alias(
                user_id=user.id,
                local_part=candidate,
                domain=domain,
                address=f"{candidate}@{domain}",
                kind=kind,
                description=description,
                recipients=recipients,
                labels=labels,
            )
            if await self._insert(alias):
                kv_sync.mark_alias(self.db, alias.id)
                return alias
        raise Conflict("That alias is already taken", code="alias_taken")

    async def list(
        self,
        user: User,
        *,
        query: str | None = None,
        state: AliasState | None = None,
        label_id: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> tuple[list[Alias], int]:
        """Search the user's aliases by address or (decrypted) description.

        Args:
            user: Owner.
            query: Case-insensitive substring of address or description.
            state: Filter by state; default shows active and inactive.
            label_id: Only aliases with this label.
            page: 1-based page number.
            per_page: Page size.
        Returns:
            (page of aliases, total matches).
        """
        stmt = self._owned_query(user).order_by(Alias.created_at.desc())
        stmt = (
            stmt.where(Alias.state == state)
            if state
            else stmt.where(Alias.state.in_(VISIBLE_STATES))
        )
        if label_id:
            stmt = stmt.where(
                Alias.id.in_(
                    select(alias_labels.c.alias_id).where(alias_labels.c.label_id == label_id)
                )
            )
        aliases = list(await self.db.scalars(stmt))
        if query:
            # Descriptions are encrypted, so text search happens after decryption.
            needle = query.strip().lower()
            aliases = [
                a for a in aliases if needle in a.address or needle in (a.description or "").lower()
            ]
        start = (page - 1) * per_page
        return aliases[start : start + per_page], len(aliases)

    async def update(
        self,
        user: User,
        alias_id: uuid.UUID,
        *,
        description: str | None = None,
        reply_enabled: bool | None = None,
        active: bool | None = None,
        recipient_ids: Sequence[uuid.UUID] | None = None,
        label_ids: Sequence[uuid.UUID] | None = None,
        clear_description: bool = False,
    ) -> Alias:
        """Change alias settings; None leaves a field untouched.

        Args:
            user: Owner.
            alias_id: Alias id.
            description: New description.
            reply_enabled: Allow replies through this alias.
            active: Activate (True) or deactivate (False).
            recipient_ids: Replace recipients (empty list = use default recipient).
            label_ids: Replace labels.
            clear_description: Remove the description.
        Returns:
            The updated alias.
        """
        alias = await self.get_owned(user, alias_id)
        if alias.state not in VISIBLE_STATES:
            raise Conflict("Restore the alias before editing it")
        if description is not None or clear_description:
            alias.description = None if clear_description else description
        if reply_enabled is not None:
            alias.reply_enabled = reply_enabled
        if recipient_ids is not None:
            alias.recipients = await self._owned_recipients(user, recipient_ids)
        if label_ids is not None:
            alias.labels = await self._owned_labels(user, label_ids)
        if active is not None:
            self._set_active(alias, active)
        await self.db.flush()
        return alias

    def _set_active(self, alias: Alias, active: bool) -> None:
        """Switch between active and inactive.

        Args:
            alias: Alias in a visible state.
            active: Target state.
        Returns:
            None.
        """
        new_state = AliasState.ACTIVE if active else AliasState.INACTIVE
        if alias.state != new_state:
            alias.state = new_state
            kv_sync.mark_alias(self.db, alias.id)

    def _soft_delete(self, alias: Alias) -> None:
        """Move an alias to the deleted state (restorable for 30 days).

        Args:
            alias: Alias in a visible state.
        Returns:
            None.
        """
        alias.state = AliasState.DELETED
        alias.deleted_at = datetime.now(UTC)
        kv_sync.mark_alias(self.db, alias.id)

    async def delete(self, user: User, alias_id: uuid.UUID) -> Alias:
        """Soft-delete an alias; the edge then rejects its mail with 550.

        Args:
            user: Owner.
            alias_id: Alias id.
        Returns:
            The alias.
        """
        alias = await self.get_owned(user, alias_id)
        if alias.state in VISIBLE_STATES:
            self._soft_delete(alias)
            await self.db.flush()
        return alias

    async def restore(self, user: User, alias_id: uuid.UUID) -> Alias:
        """Undo a deletion within the restore window (restored as inactive).

        Args:
            user: Owner.
            alias_id: Alias id.
        Returns:
            The alias. Raises Conflict outside the window or for non-deleted aliases.
        """
        alias = await self.get_owned(user, alias_id)
        if alias.state != AliasState.DELETED or alias.deleted_at is None:
            raise Conflict("Only deleted aliases can be restored")
        if alias.deleted_at + RESTORE_WINDOW < datetime.now(UTC):
            raise Conflict("The 30-day restore window has passed")
        alias.state = AliasState.INACTIVE
        alias.deleted_at = None
        kv_sync.mark_alias(self.db, alias.id)
        await self.db.flush()
        return alias

    async def forget(self, user: User, alias_id: uuid.UUID) -> None:
        """Permanently detach an alias from the user; its address stays reserved forever.

        Args:
            user: Owner.
            alias_id: Alias id.
        Returns:
            None.
        """
        alias = await self.get_owned(user, alias_id)
        alias.state = AliasState.FORGOTTEN
        alias.deleted_at = alias.deleted_at or datetime.now(UTC)
        alias.user_id = None
        alias.description = None
        alias.recipients = []
        alias.labels = []
        kv_sync.mark_alias(self.db, alias.id)
        await self.db.flush()

    async def bulk(self, user: User, ids: Sequence[uuid.UUID], action: str) -> int:
        """Apply activate/deactivate/delete to up to 100 owned aliases.

        Args:
            user: Owner.
            ids: Alias ids (all must be owned).
            action: "activate", "deactivate" or "delete".
        Returns:
            Number of aliases changed.
        """
        unique_ids = set(ids)
        if not unique_ids or len(unique_ids) > BULK_LIMIT:
            raise ValidationFailed(f"Select between 1 and {BULK_LIMIT} aliases")
        aliases = list(
            await self.db.scalars(
                select(Alias).where(Alias.id.in_(unique_ids), Alias.user_id == user.id)
            )
        )
        if len(aliases) != len(unique_ids):
            raise NotFound("One or more aliases were not found")
        changed = 0
        for alias in aliases:
            if alias.state not in VISIBLE_STATES:
                continue
            before = alias.state
            if action == "delete":
                self._soft_delete(alias)
            else:
                self._set_active(alias, action == "activate")
            changed += alias.state != before
        await self.db.flush()
        return changed

    async def count_for(self, user: User) -> int:
        """Number of visible aliases a user has.

        Args:
            user: Owner.
        Returns:
            The count.
        """
        count = await self.db.scalar(
            select(func.count())
            .select_from(Alias)
            .where(Alias.user_id == user.id, Alias.state.in_(VISIBLE_STATES))
        )
        return int(count or 0)
