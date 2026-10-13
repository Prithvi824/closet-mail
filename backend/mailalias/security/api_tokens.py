"""API token format "ma_<prefix>_<secret>": generation, parsing and secret hashing."""

# 1st party imports
import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass

TOKEN_TAG = "ma"
PREFIX_LENGTH = 8
SECRET_LENGTH = 32
ALPHABET = string.ascii_lowercase + string.digits
SCOPES = frozenset({"aliases:read", "aliases:write", "recipients:read", "contacts:write"})


@dataclass(frozen=True)
class NewToken:
    """A freshly generated token; `value` is shown to the user once and never stored."""

    value: str
    prefix: str
    secret_hash: str


def _random(length: int) -> str:
    """Random lowercase alphanumeric string (no "_" so the format stays parseable).

    Args:
        length: Characters.
    Returns:
        The string.
    """
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_secret(secret: str) -> str:
    """SHA-256 of the secret (it is random and long, so no slow hash is needed).

    Args:
        secret: Secret part of the token.
    Returns:
        Hex digest.
    """
    return hashlib.sha256(secret.encode()).hexdigest()


def generate() -> NewToken:
    """Create a new token.

    Returns:
        The token value, its public prefix and the secret hash.
    """
    prefix, secret = _random(PREFIX_LENGTH), _random(SECRET_LENGTH)
    return NewToken(f"{TOKEN_TAG}_{prefix}_{secret}", prefix, hash_secret(secret))


def parse(value: str) -> tuple[str, str] | None:
    """Split a presented token into (prefix, secret).

    Args:
        value: Bearer token.
    Returns:
        (prefix, secret), or None when the format is wrong.
    """
    parts = value.strip().split("_")
    if len(parts) != 3 or parts[0] != TOKEN_TAG:
        return None
    prefix, secret = parts[1], parts[2]
    if len(prefix) != PREFIX_LENGTH or len(secret) != SECRET_LENGTH:
        return None
    return prefix, secret


def secret_matches(secret: str, secret_hash: str) -> bool:
    """Constant-time comparison of a presented secret with the stored hash.

    Args:
        secret: Presented secret.
        secret_hash: Stored hash.
    Returns:
        True on match.
    """
    return hmac.compare_digest(hash_secret(secret), secret_hash)
