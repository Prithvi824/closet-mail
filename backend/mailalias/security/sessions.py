"""Server-side login sessions stored in Redis, referenced by the `ma_session` cookie."""

# 1st party imports
import json
import secrets
import time
import uuid
from dataclasses import asdict, dataclass

# 3rd party imports
from redis.asyncio import Redis

SESSION_COOKIE = "ma_session"
SESSION_TTL_SECONDS = 14 * 86_400
_SESSION_KEY = "sess:{sid}"
_USER_INDEX_KEY = "usess:{user_id}"


@dataclass
class SessionData:
    """What a session remembers about the browser."""

    user_id: str
    mfa_passed: bool
    created: float
    webauthn_challenge: str | None = None


class SessionStore:
    """Create, read, update and revoke sessions; tracks each user's session ids."""

    def __init__(self, redis: Redis) -> None:
        """Build the store.

        Args:
            redis: Async Redis client (decode_responses=True).
        Returns:
            None.
        """
        self._redis = redis

    async def create(self, user_id: uuid.UUID, mfa_passed: bool) -> str:
        """Start a new session.

        Args:
            user_id: The authenticated user.
            mfa_passed: Whether the second factor is already satisfied.
        Returns:
            The new opaque session id (cookie value).
        """
        sid = secrets.token_urlsafe(32)
        data = SessionData(user_id=str(user_id), mfa_passed=mfa_passed, created=time.time())
        index_key = _USER_INDEX_KEY.format(user_id=user_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(_SESSION_KEY.format(sid=sid), json.dumps(asdict(data)), ex=SESSION_TTL_SECONDS)
            pipe.sadd(index_key, sid)
            pipe.expire(index_key, SESSION_TTL_SECONDS)
            await pipe.execute()
        return sid

    async def get(self, sid: str) -> SessionData | None:
        """Load a session.

        Args:
            sid: Session id from the cookie.
        Returns:
            The session data, or None if missing/expired.
        """
        raw = await self._redis.get(_SESSION_KEY.format(sid=sid))
        return SessionData(**json.loads(raw)) if raw else None

    async def save(self, sid: str, data: SessionData) -> None:
        """Overwrite a session's data, keeping its remaining lifetime.

        Args:
            sid: Session id.
            data: New data.
        Returns:
            None.
        """
        await self._redis.set(_SESSION_KEY.format(sid=sid), json.dumps(asdict(data)), keepttl=True)

    async def delete(self, sid: str) -> None:
        """Revoke one session.

        Args:
            sid: Session id.
        Returns:
            None.
        """
        data = await self.get(sid)
        await self._redis.delete(_SESSION_KEY.format(sid=sid))
        if data:
            await self._redis.srem(_USER_INDEX_KEY.format(user_id=data.user_id), sid)

    async def delete_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke every session of a user (password reset, disable, MFA change).

        Args:
            user_id: The user.
        Returns:
            None.
        """
        index_key = _USER_INDEX_KEY.format(user_id=user_id)
        sids = await self._redis.smembers(index_key)
        keys = [_SESSION_KEY.format(sid=sid) for sid in sids]
        await self._redis.delete(index_key, *keys)
