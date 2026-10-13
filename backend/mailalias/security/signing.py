"""Signed, expiring tokens for one-click action links (banner "block sender" etc.)."""

# 1st party imports
from typing import Any

# 3rd party imports
from itsdangerous import BadSignature, URLSafeTimedSerializer

# local imports
from mailalias.config import get_settings

ACTION_SALT = "action"
SECONDS_PER_DAY = 86_400


class InvalidActionToken(Exception):
    """The token was tampered with, expired, or signed with another key."""


def _serializer(salt: str) -> URLSafeTimedSerializer:
    """Build a serializer keyed with SIGNING_KEY.

    Args:
        salt: Namespace separating token purposes.
    Returns:
        A URLSafeTimedSerializer.
    """
    return URLSafeTimedSerializer(get_settings().signing_key.get_secret_value(), salt=salt)


def sign_action(payload: dict[str, Any]) -> str:
    """Sign an action payload for embedding in a URL.

    Args:
        payload: JSON-serialisable data, e.g. {"a": "block_contact", "id": ..., "uid": ...}.
    Returns:
        A URL-safe signed token.
    """
    return _serializer(ACTION_SALT).dumps(payload)


def load_action(token: str, max_age_days: int = 90) -> dict[str, Any]:
    """Verify and decode an action token.

    Args:
        token: Token from `sign_action`.
        max_age_days: Maximum token age.
    Returns:
        The payload dict. Raises InvalidActionToken if invalid or expired.
    """
    try:
        payload = _serializer(ACTION_SALT).loads(token, max_age=max_age_days * SECONDS_PER_DAY)
    except BadSignature as exc:  # SignatureExpired is a subclass
        raise InvalidActionToken(type(exc).__name__) from exc
    if not isinstance(payload, dict):
        raise InvalidActionToken("payload is not an object")
    return payload
