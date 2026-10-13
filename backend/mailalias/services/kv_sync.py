"""Mirror alias/token/subdomain validity into Workers KV for the edge Worker.

Services mark changed objects on the DB session; after a successful commit the marks are
dispatched as Celery tasks, which write KV. A periodic reconcile repairs any drift.
"""

# 1st party imports
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

# local imports
from mailalias.integrations.cloudflare_kv import CloudflareKv
from mailalias.models import Alias, AliasState, Contact, User
from mailalias.services import task_dispatch

logger = logging.getLogger(__name__)

PENDING_KEY = "kv_sync_pending"
LAST_RECONCILE_KEY = "kv:last_reconcile"
ALIAS_PREFIX, TOKEN_PREFIX, SUBDOMAIN_PREFIX = "a:", "r:", "s:"
TASK_BY_KIND = {
    "alias": "kv.sync_alias",
    "contact": "kv.sync_contact",
    "subdomain": "kv.sync_subdomain",
}


def _mark(db: AsyncSession, kind: str, object_id: uuid.UUID) -> None:
    """Remember that an object's KV entry must be refreshed after commit.

    Args:
        db: Session the change is made in.
        kind: "alias", "contact" or "subdomain".
        object_id: Alias, contact or user id.
    Returns:
        None.
    """
    pending: set[tuple[str, str]] = db.info.setdefault(PENDING_KEY, set())
    pending.add((kind, str(object_id)))


def mark_alias(db: AsyncSession, alias_id: uuid.UUID) -> None:
    """Queue a KV refresh of one alias address after commit.

    Args:
        db: Session.
        alias_id: Alias id.
    Returns:
        None.
    """
    _mark(db, "alias", alias_id)


def mark_contact(db: AsyncSession, contact_id: uuid.UUID) -> None:
    """Queue a KV refresh of one reply token after commit.

    Args:
        db: Session.
        contact_id: Contact id.
    Returns:
        None.
    """
    _mark(db, "contact", contact_id)


def mark_subdomain(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Queue a KV refresh of a user's subdomain catch-all flag after commit.

    Args:
        db: Session.
        user_id: User id.
    Returns:
        None.
    """
    _mark(db, "subdomain", user_id)


@event.listens_for(Session, "after_commit")
def _dispatch_after_commit(session: Session) -> None:
    """Send queued KV tasks once data is committed; failures are left to reconcile.

    Args:
        session: The sync session behind an AsyncSession.
    Returns:
        None.
    """
    pending: set[tuple[str, str]] = session.info.pop(PENDING_KEY, set())
    for kind, object_id in sorted(pending):
        try:
            task_dispatch.dispatch(TASK_BY_KIND[kind], object_id)
        except Exception:  # broker down must never fail the API; reconcile repairs KV
            logger.exception("kv dispatch failed", extra={"kind": kind, "object_id": object_id})


@event.listens_for(Session, "after_rollback")
def _clear_after_rollback(session: Session) -> None:
    """Drop queued KV work when the transaction is rolled back.

    Args:
        session: The sync session.
    Returns:
        None.
    """
    session.info.pop(PENDING_KEY, None)


def alias_value(alias: Alias) -> str:
    """KV value for an alias state.

    Args:
        alias: The alias.
    Returns:
        "A" active, "I" inactive, "D" deleted or forgotten.
    """
    return {AliasState.ACTIVE: "A", AliasState.INACTIVE: "I"}.get(alias.state, "D")


async def sync_alias(db: AsyncSession, kv: CloudflareKv, alias_id: uuid.UUID) -> None:
    """Write one alias's KV entry from the database state.

    Args:
        db: Session.
        kv: KV client.
        alias_id: Alias id.
    Returns:
        None.
    """
    alias = await db.get(Alias, alias_id)
    if alias is not None:
        await kv.put(ALIAS_PREFIX + alias.address, alias_value(alias))


async def sync_contact(db: AsyncSession, kv: CloudflareKv, contact_id: uuid.UUID) -> None:
    """Write (or delete) one reply token's KV entry.

    Args:
        db: Session.
        kv: KV client.
        contact_id: Contact id.
    Returns:
        None.
    """
    contact = await db.get(Contact, contact_id)
    if contact is not None:
        await kv.put(TOKEN_PREFIX + contact.token, "V")


def subdomain_enabled(user: User) -> bool:
    """Whether the user's personal subdomain should accept unknown addresses.

    Args:
        user: The user.
    Returns:
        True when catch-all is on and the account is enabled.
    """
    return user.subdomain_catchall and user.disabled_at is None


async def sync_subdomain(db: AsyncSession, kv: CloudflareKv, user_id: uuid.UUID) -> None:
    """Write or delete the `s:<username>` catch-all flag.

    Args:
        db: Session.
        kv: KV client.
        user_id: User id.
    Returns:
        None.
    """
    user = await db.get(User, user_id)
    if user is None:
        return
    if subdomain_enabled(user):
        await kv.put(SUBDOMAIN_PREFIX + user.username, "C")
    else:
        await kv.delete(SUBDOMAIN_PREFIX + user.username)


async def desired_state(db: AsyncSession) -> dict[str, str]:
    """Compute every KV entry the edge should have, from the database.

    Args:
        db: Session.
    Returns:
        Mapping of KV key to value.
    """
    desired: dict[str, str] = {}
    for alias in await db.scalars(select(Alias)):
        desired[ALIAS_PREFIX + alias.address] = alias_value(alias)
    for token in await db.scalars(select(Contact.token)):
        desired[TOKEN_PREFIX + token] = "V"
    for user in await db.scalars(select(User)):
        if subdomain_enabled(user):
            desired[SUBDOMAIN_PREFIX + user.username] = "C"
    return desired


async def reconcile(
    db: AsyncSession, kv: CloudflareKv, redis: Redis, *, delete_extra: bool
) -> dict[str, Any]:
    """Rewrite all desired keys, optionally delete unknown ones, and record drift in Redis.

    Args:
        db: Session.
        kv: KV client.
        redis: Redis for the `kv:last_reconcile` summary.
        delete_extra: Remove keys the DB does not know. Only safe against the production DB,
            because dev and prod share one KV namespace.
    Returns:
        Summary {"at", "keys", "missing", "extra", "deleted"}.
    """
    desired = await desired_state(db)
    actual: set[str] = set()
    for prefix in (ALIAS_PREFIX, TOKEN_PREFIX, SUBDOMAIN_PREFIX):
        actual.update([key async for key in kv.list_keys(prefix)])
    extra = sorted(actual - desired.keys())
    missing = len(desired.keys() - actual)
    # Values cannot be listed cheaply, so rewrite every desired key (small at internal scale).
    if desired:
        await kv.bulk_put(desired)
    if extra and delete_extra:
        await kv.bulk_delete(extra)
    summary = {
        "at": datetime.now(UTC).isoformat(),
        "keys": len(desired),
        "missing": missing,
        "extra": len(extra),
        "deleted": delete_extra,
    }
    await redis.set(LAST_RECONCILE_KEY, json.dumps(summary))
    return summary
