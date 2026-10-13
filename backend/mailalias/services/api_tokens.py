"""API tokens: create, list, revoke, and authenticate bearer requests."""

# 1st party imports
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

# 3rd party imports
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import NotFound, ValidationFailed
from mailalias.models import ApiToken, User
from mailalias.security import api_tokens
from mailalias.services import audit

MAX_TOKENS_PER_USER = 20
LAST_USED_RESOLUTION = timedelta(minutes=1)


class TokenService:
    """Per-user API tokens; only the prefix and a hash of the secret are stored."""

    def __init__(self, db: AsyncSession) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
        Returns:
            None.
        """
        self.db = db

    async def list(self, user: User) -> list[ApiToken]:
        """The user's tokens, newest first.

        Args:
            user: Owner.
        Returns:
            Tokens (without secrets).
        """
        query = (
            select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
        )
        return list(await self.db.scalars(query))

    async def create(
        self, user: User, name: str, scopes: Sequence[str], expires_in_days: int | None
    ) -> tuple[ApiToken, str]:
        """Issue a token.

        Args:
            user: Owner.
            name: Label shown in the list.
            scopes: Granted scopes (subset of api_tokens.SCOPES).
            expires_in_days: Lifetime, or None for no expiry.
        Returns:
            (row, full token value to show once). Raises ValidationFailed.
        """
        unknown = set(scopes) - api_tokens.SCOPES
        if not scopes or unknown:
            raise ValidationFailed("Choose at least one valid scope")
        count = await self.db.scalar(
            select(func.count()).select_from(ApiToken).where(ApiToken.user_id == user.id)
        )
        if (count or 0) >= MAX_TOKENS_PER_USER:
            raise ValidationFailed(f"At most {MAX_TOKENS_PER_USER} tokens; revoke an old one")
        new = api_tokens.generate()
        token = ApiToken(
            user_id=user.id,
            name=name.strip(),
            prefix=new.prefix,
            secret_hash=new.secret_hash,
            scopes=sorted(set(scopes)),
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days
            else None,
        )
        self.db.add(token)
        await self.db.flush()
        await audit.record(
            self.db,
            "token.create",
            user_id=user.id,
            target_type="api_token",
            target_id=str(token.id),
        )
        return token, new.value

    async def revoke(self, user: User, token_id: uuid.UUID) -> None:
        """Delete a token.

        Args:
            user: Owner.
            token_id: Token id.
        Returns:
            None. Raises NotFound.
        """
        token = await self.db.get(ApiToken, token_id)
        if token is None or token.user_id != user.id:
            raise NotFound("Token not found")
        await self.db.delete(token)
        await audit.record(
            self.db,
            "token.revoke",
            user_id=user.id,
            target_type="api_token",
            target_id=str(token_id),
        )

    async def authenticate(self, value: str) -> tuple[ApiToken, User] | None:
        """Check a bearer token; records use at most once a minute.

        Args:
            value: Presented token.
        Returns:
            (token, user) when valid, unexpired and the user is enabled; else None.
        """
        parsed = api_tokens.parse(value)
        if parsed is None:
            return None
        prefix, secret = parsed
        token = await self.db.scalar(select(ApiToken).where(ApiToken.prefix == prefix))
        now = datetime.now(UTC)
        if token is None or not api_tokens.secret_matches(secret, token.secret_hash):
            return None
        if token.expires_at is not None and token.expires_at <= now:
            return None
        user = await self.db.get(User, token.user_id)
        if user is None or user.disabled_at is not None:
            return None
        if token.last_used_at is None or now - token.last_used_at >= LAST_USED_RESOLUTION:
            await self.db.execute(
                update(ApiToken).where(ApiToken.id == token.id).values(last_used_at=now)
            )
            await self.db.commit()
        return token, user
