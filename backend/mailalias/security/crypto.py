"""Column encryption (Fernet) and keyed lookup hashes (HMAC-SHA256) for personal data."""

# 1st party imports
import hashlib
import hmac
from functools import lru_cache
from typing import Any

# 3rd party imports
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Dialect, Text
from sqlalchemy.types import TypeDecorator

# local imports
from mailalias.config import get_settings


@lru_cache
def _fernet() -> MultiFernet:
    """Build the cipher from DATA_ENCRYPTION_KEY (comma-separated; first key encrypts).

    Returns:
        A MultiFernet so old keys keep decrypting after a rotation.
    """
    keys = get_settings().data_encryption_key.get_secret_value().split(",")
    return MultiFernet([Fernet(key.strip()) for key in keys if key.strip()])


@lru_cache
def _hash_key() -> bytes:
    """Decode HASH_KEY (hex) into raw bytes.

    Returns:
        The HMAC key bytes.
    """
    return bytes.fromhex(get_settings().hash_key.get_secret_value())


def encrypt(plaintext: str) -> str:
    """Encrypt a string with the data key.

    Args:
        plaintext: Value to protect.
    Returns:
        The Fernet token as text.
    """
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token produced by `encrypt`.

    Args:
        token: Ciphertext from the database.
    Returns:
        The original plaintext. Raises cryptography.fernet.InvalidToken on tampering.
    """
    return _fernet().decrypt(token.encode()).decode()


def encrypt_bytes(data: bytes) -> bytes:
    """Encrypt raw bytes (e.g. a quarantined message) with the data key.

    Args:
        data: Bytes to protect.
    Returns:
        The Fernet token bytes.
    """
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """Decrypt bytes produced by `encrypt_bytes`.

    Args:
        token: Fernet token bytes.
    Returns:
        The original bytes. Raises cryptography.fernet.InvalidToken on tampering.
    """
    return _fernet().decrypt(token)


def normalize_lookup(value: str) -> str:
    """Normalise a value before hashing so lookups are case- and whitespace-insensitive.

    Args:
        value: Raw value, e.g. an email address.
    Returns:
        The stripped, lowercased value.
    """
    return value.strip().lower()


def lookup_hash(value: str) -> str:
    """Keyed hash used to find rows by an encrypted value without decrypting.

    Args:
        value: Raw value; it is normalised first.
    Returns:
        The HMAC-SHA256 hex digest (64 chars).
    """
    digest = hmac.new(_hash_key(), normalize_lookup(value).encode(), hashlib.sha256)
    return digest.hexdigest()


class EncryptedString(TypeDecorator[str]):
    """Text column transparently encrypted with Fernet at rest."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Encrypt on the way into the database.

        Args:
            value: Plaintext or None.
            dialect: SQLAlchemy dialect (unused).
        Returns:
            Ciphertext or None.
        """
        return None if value is None else encrypt(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        """Decrypt on the way out of the database.

        Args:
            value: Ciphertext or None.
            dialect: SQLAlchemy dialect (unused).
        Returns:
            Plaintext or None.
        """
        return None if value is None else decrypt(str(value))
