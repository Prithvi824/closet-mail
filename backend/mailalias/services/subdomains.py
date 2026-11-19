"""Subdomains: the operator creates, edits, suspends and retires the subdomains it serves."""

# 1st party imports
import builtins
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound, ValidationFailed
from mailalias.config import Settings
from mailalias.mail.addresses import is_valid_username
from mailalias.models import (
    Alias,
    AliasState,
    MailLog,
    Recipient,
    SubdomainState,
    SubdomainStatus,
    UsageDaily,
    User,
    UserRole,
)
from mailalias.schemas.subdomains import SubdomainResponse, SubdomainStatusOut
from mailalias.services import audit, kv_sync
from mailalias.services.aliases import AliasService
from mailalias.services.quota import share_key, share_limit
from mailalias.services.recipients import RecipientService
from mailalias.services.system_mail import SystemMailService

# users.limits keys the operator may override per subdomain.
SUBDOMAIN_LIMIT_KEYS = frozenset(
    {"forwards_per_hour", "replies_per_day", "sends_per_day", "catchall_creates_per_day"}
)


def _clean(value: str | None) -> str | None:
    """Trim free text; empty becomes None.

    Args:
        value: Raw text.
    Returns:
        Trimmed text or None.
    """
    value = (value or "").strip()
    return value or None


class SubdomainService:
    """Operator-side lifecycle of subdomains (each one a users row)."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
            settings: Alias domain and limits.
        Returns:
            None.
        """
        self.db = db
        self.settings = settings

    async def list(self) -> builtins.list[User]:
        """Every subdomain, the operator's own first, then by label.

        Returns:
            Users rows.
        """
        query = select(User).order_by(User.role != UserRole.ADMIN, User.username)
        return builtins.list(await self.db.scalars(query))

    async def get(self, label: str) -> User:
        """One subdomain by label.

        Args:
            label: Subdomain label.
        Returns:
            The users row. Raises NotFound.
        """
        user = await self.db.scalar(select(User).where(User.username == label.strip().lower()))
        if user is None:
            raise NotFound("Subdomain not found")
        return user

    async def create(
        self,
        *,
        label: str,
        display_name: str | None,
        inbox_email: str,
        notes: str | None,
        mail: SystemMailService,
        actor: User,
    ) -> User:
        """Create a subdomain (no login) with catch-all on and its first, default inbox.

        Args:
            label, display_name, notes: Identity of the subdomain.
            inbox_email, mail: First inbox, emailed a verification link.
            actor: Operator (audited).
        Returns:
            The new users row. Raises ValidationFailed or Conflict.
        """
        label = label.strip().lower()
        if not is_valid_username(label):
            raise ValidationFailed("This label is not allowed", code="invalid_label")
        if await self.db.scalar(select(User.id).where(User.username == label)):
            raise Conflict("This label is already taken", code="label_taken")
        user = User(
            username=label,
            role=UserRole.USER,
            display_name=_clean(display_name),
            notes=_clean(notes),
            subdomain_catchall=True,
        )
        self.db.add(user)
        await self.db.flush()
        recipient = await RecipientService(self.db).add(user, inbox_email, mail)
        recipient.forward_by_default = True
        kv_sync.mark_subdomain(self.db, user.id)
        await audit.record(
            self.db,
            "subdomain.created",
            user_id=user.id,
            actor_id=actor.id,
            target_type="subdomain",
            target_id=label,
        )
        await self.db.flush()
        return user

    async def update(
        self,
        label: str,
        *,
        display_name: str | None = None,
        notes: str | None = None,
        suspended: bool | None = None,
        limits: Mapping[str, int] | None = None,
        clear_limits: bool = False,
        actor: User,
    ) -> User:
        """Edit the name, notes and limits, or suspend/resume a subdomain.

        Args:
            label: Subdomain label.
            display_name, notes, suspended, limits: New values; None leaves them unchanged.
            clear_limits, actor: Reset every limit first; operator (audited).
        Returns:
            The users row. Raises NotFound, ValidationFailed or Conflict.
        """
        user = await self.get(label)
        if suspended is not None:
            self._ensure_not_operator(user, "suspended")
            if user.retired_at is not None:
                raise Conflict("This subdomain is retired", code="retired")
        if limits is not None:
            unknown = set(limits) - SUBDOMAIN_LIMIT_KEYS
            if unknown:
                raise ValidationFailed(f"Unknown limits: {', '.join(sorted(unknown))}")
            if any(value < 1 for value in limits.values()):
                raise ValidationFailed("Limits must be positive whole numbers")
        if display_name is not None:
            user.display_name = _clean(display_name)
        if notes is not None:
            user.notes = _clean(notes)
        if clear_limits:
            user.limits = None
        if limits:
            user.limits = {**(user.limits or {}), **limits}
        if suspended is not None and suspended != (user.disabled_at is not None):
            user.disabled_at = datetime.now(UTC) if suspended else None
            # The edge's catch-all flag depends on the subdomain being active.
            kv_sync.mark_subdomain(self.db, user.id)
        await audit.record(
            self.db,
            "subdomain.updated",
            user_id=user.id,
            actor_id=actor.id,
            target_type="subdomain",
            target_id=user.username,
        )
        await self.db.flush()
        return user

    async def retire(self, label: str, *, actor: User) -> User:
        """Stop a subdomain for good: aliases forgotten (still reserved), inboxes disabled.

        Args:
            label: Subdomain label.
            actor: Operator (audited).
        Returns:
            The users row (nothing is deleted). Raises NotFound or Conflict.
        """
        user = await self.get(label)
        self._ensure_not_operator(user, "retired")
        if user.retired_at is not None:
            return user
        now = datetime.now(UTC)
        user.retired_at = now
        user.disabled_at = user.disabled_at or now
        user.subdomain_catchall = False
        aliases = AliasService(self.db, self.settings)
        for alias_id in builtins.list(
            await self.db.scalars(select(Alias.id).where(Alias.user_id == user.id))
        ):
            await aliases.forget(user, alias_id)
        await self.db.execute(
            update(Recipient)
            .where(Recipient.user_id == user.id, Recipient.disabled_at.is_(None))
            .values(disabled_at=now)
        )
        kv_sync.mark_subdomain(self.db, user.id)
        await audit.record(
            self.db,
            "subdomain.retired",
            user_id=user.id,
            actor_id=actor.id,
            target_type="subdomain",
            target_id=user.username,
        )
        await self.db.flush()
        return user

    @staticmethod
    def _ensure_not_operator(user: User, change: str) -> None:
        """Refuse to suspend or retire the operator's own subdomain.

        Args:
            user: Target subdomain.
            change: What was asked ("suspended" or "retired"), for the message.
        Returns:
            None. Raises Conflict (code operator_subdomain).
        """
        if user.role == UserRole.ADMIN:
            raise Conflict(f"Your own subdomain can't be {change}", code="operator_subdomain")


def effective_state(user: User, status: SubdomainStatus | None) -> SubdomainState:
    """The state to show: retired and suspended win over the last routing check.

    Args:
        user: Subdomain.
        status: Its last check, if any.
    Returns:
        The state.
    """
    if user.retired_at is not None:
        return SubdomainState.RETIRED
    if user.disabled_at is not None:
        return SubdomainState.SUSPENDED
    return status.state if status is not None else SubdomainState.UNKNOWN


async def build_responses(
    db: AsyncSession, redis: Redis, settings: Settings, users: Sequence[User]
) -> builtins.list[SubdomainResponse]:
    """Subdomain views with counts, today's numbers and status, in a fixed number of queries.

    Args:
        db, redis, settings: Session, Redis (send shares), settings (domain, default share).
        users: Subdomains to describe, in the order to return them.
    Returns:
        One response per user.
    """
    ids = [user.id for user in users]
    if not ids:
        return []
    usable_default = and_(
        Recipient.forward_by_default.is_(True),
        Recipient.verified_at.is_not(None),
        Recipient.disabled_at.is_(None),
    )
    inboxes = {
        row[0]: (int(row[1]), int(row[2]))
        for row in await db.execute(
            select(Recipient.user_id, func.count(), func.count().filter(usable_default))
            .where(Recipient.user_id.in_(ids))
            .group_by(Recipient.user_id)
        )
    }
    aliases = dict(
        (
            await db.execute(
                select(Alias.user_id, func.count())
                .where(
                    Alias.user_id.in_(ids),
                    Alias.state.in_((AliasState.ACTIVE, AliasState.INACTIVE)),
                )
                .group_by(Alias.user_id)
            )
        ).all()
    )
    today = datetime.now(UTC).date()
    received = dict(
        (
            await db.execute(
                select(UsageDaily.user_id, UsageDaily.received).where(
                    UsageDaily.user_id.in_(ids), UsageDaily.day == today
                )
            )
        ).all()
    )
    last_mail = dict(
        (
            await db.execute(
                select(MailLog.user_id, func.max(MailLog.received_at))
                .where(MailLog.user_id.in_(ids))
                .group_by(MailLog.user_id)
            )
        ).all()
    )
    statuses = {
        row.user_id: row
        for row in await db.scalars(select(SubdomainStatus).where(SubdomainStatus.user_id.in_(ids)))
    }
    sends = await redis.mget([share_key(user_id) for user_id in ids])
    responses = []
    for user, sent in zip(users, sends, strict=True):
        status = statuses.get(user.id)
        inbox_count, default_count = inboxes.get(user.id, (0, 0))
        responses.append(
            SubdomainResponse(
                id=user.id,
                label=user.username,
                domain=f"{user.username}.{settings.alias_domain}",
                display_name=user.display_name,
                notes=user.notes,
                is_operator=user.role == UserRole.ADMIN,
                suspended=user.disabled_at is not None and user.retired_at is None,
                retired=user.retired_at is not None,
                catchall=user.subdomain_catchall,
                inbox_count=inbox_count,
                default_inbox_count=default_count,
                alias_count=int(aliases.get(user.id, 0)),
                received_today=int(received.get(user.id, 0)),
                sends_today=int(sent or 0),
                send_share=share_limit(settings, user.limits),
                limits=user.limits,
                status=SubdomainStatusOut(
                    state=effective_state(user, status),
                    mx_ok=status.mx_ok if status else None,
                    spf_ok=status.spf_ok if status else None,
                    kv_ok=status.kv_ok if status else None,
                    detail=status.detail if status else None,
                    checked_at=status.checked_at if status else None,
                    last_mail_at=last_mail.get(user.id),
                ),
                created_at=user.created_at,
            )
        )
    return responses
