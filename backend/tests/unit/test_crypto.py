"""Tests for column encryption, lookup hashes and password hashing."""

# 3rd party imports
import pytest
from cryptography.fernet import InvalidToken

# local imports
from mailalias.security.crypto import EncryptedString, decrypt, encrypt, lookup_hash
from mailalias.security.passwords import hash_password, verify_password


def test_encrypt_round_trip_and_ciphertext_differs() -> None:
    """Encrypting then decrypting returns the input; ciphertext hides it and is randomised.

    Returns:
        None.
    """
    secret = "alice@example.com"
    token = encrypt(secret)
    assert secret not in token
    assert encrypt(secret) != token
    assert decrypt(token) == secret


def test_decrypt_rejects_tampered_token() -> None:
    """A modified ciphertext fails authentication.

    Returns:
        None.
    """
    token = encrypt("value")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(InvalidToken):
        decrypt(tampered)


def test_encrypted_string_type_round_trip() -> None:
    """The SQLAlchemy type encrypts on bind and decrypts on result, passing None through.

    Returns:
        None.
    """
    column_type = EncryptedString()
    stored = column_type.process_bind_param("Bob", dialect=None)  # type: ignore[arg-type]
    assert stored is not None and stored != "Bob"
    assert column_type.process_result_value(stored, dialect=None) == "Bob"  # type: ignore[arg-type]
    assert column_type.process_bind_param(None, dialect=None) is None  # type: ignore[arg-type]


def test_lookup_hash_is_stable_and_case_insensitive() -> None:
    """Hashes are deterministic, normalised, and differ for different values.

    Returns:
        None.
    """
    digest = lookup_hash("Alice@Example.com ")
    assert digest == lookup_hash("alice@example.com")
    assert len(digest) == 64
    assert digest != lookup_hash("bob@example.com")


def test_password_hash_verify() -> None:
    """Correct passwords verify; wrong passwords and garbage hashes do not.

    Returns:
        None.
    """
    stored = hash_password("correct horse")
    assert verify_password(stored, "correct horse")
    assert not verify_password(stored, "wrong")
    assert not verify_password("not-a-hash", "correct horse")
