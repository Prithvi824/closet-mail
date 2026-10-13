"""Personal API tokens (managed from a browser session only; tokens cannot create tokens)."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Response, status

# local imports
from mailalias.api.deps import CurrentUser, DbSession
from mailalias.schemas.tokens import TokenCreate, TokenCreated, TokenResponse
from mailalias.services.api_tokens import TokenService

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.get("")
async def list_tokens(user: CurrentUser, db: DbSession) -> list[TokenResponse]:
    """List the user's tokens.

    Args:
        user, db: Request dependencies.
    Returns:
        Tokens, newest first (no secrets).
    """
    return [TokenResponse.build(token) for token in await TokenService(db).list(user)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_token(body: TokenCreate, user: CurrentUser, db: DbSession) -> TokenCreated:
    """Create a token; the full value is in this response only.

    Args:
        body: Name, scopes and lifetime.
        user, db: Request dependencies.
    Returns:
        The token including its secret value.
    """
    token, value = await TokenService(db).create(user, body.name, body.scopes, body.expires_in_days)
    await db.commit()
    return TokenCreated(**TokenResponse.build(token).model_dump(), token=value)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Revoke a token immediately.

    Args:
        token_id: Token id.
        user, db: Request dependencies.
    Returns:
        204 No Content.
    """
    await TokenService(db).revoke(user, token_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
