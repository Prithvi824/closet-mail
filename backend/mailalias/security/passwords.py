"""Password and one-time-code hashing with Argon2id."""

# 3rd party imports
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password (or backup code) with Argon2id.

    Args:
        password: The plaintext secret.
    Returns:
        The encoded Argon2 hash, including salt and parameters.
    """
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a plaintext secret against a stored Argon2 hash.

    Args:
        password_hash: Hash produced by `hash_password`.
        password: Candidate plaintext.
    Returns:
        True if it matches, False otherwise (never raises on mismatch or bad hash).
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether a stored hash uses outdated parameters and should be upgraded at next login.

    Args:
        password_hash: Hash produced by `hash_password`.
    Returns:
        True if the hash should be recomputed.
    """
    return _hasher.check_needs_rehash(password_hash)
