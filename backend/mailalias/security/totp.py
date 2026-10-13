"""TOTP second factor and one-time backup codes."""

# 1st party imports
import secrets

# 3rd party imports
import pyotp

# local imports
from mailalias.security.passwords import hash_password, verify_password

ISSUER = "closetcompute.online"
BACKUP_CODE_COUNT = 10


def new_secret() -> str:
    """Generate a TOTP shared secret.

    Returns:
        A base32 secret.
    """
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    """Build the otpauth:// URI shown as a QR code.

    Args:
        secret: Base32 secret.
        username: Account name shown in the authenticator app.
    Returns:
        The otpauth URI.
    """
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    """Check a 6-digit code, allowing one 30 s step of clock drift.

    Args:
        secret: Base32 secret.
        code: User-entered code (spaces ignored).
    Returns:
        True if valid now.
    """
    cleaned = code.replace(" ", "")
    return cleaned.isdigit() and pyotp.TOTP(secret).verify(cleaned, valid_window=1)


def new_backup_codes() -> tuple[list[str], list[str]]:
    """Generate one-time backup codes.

    Returns:
        (plaintext codes "xxxx-xxxx" to show once, their Argon2 hashes to store).
    """
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(BACKUP_CODE_COUNT)]
    return codes, [hash_password(code) for code in codes]


def consume_backup_code(hashes: list[str], code: str) -> list[str] | None:
    """Match a backup code against stored hashes.

    Args:
        hashes: Stored hashes.
        code: User-entered code.
    Returns:
        The remaining hashes (with the used one removed), or None if no match.
    """
    cleaned = code.strip().lower()
    for index, stored in enumerate(hashes):
        if verify_password(stored, cleaned):
            return hashes[:index] + hashes[index + 1 :]
    return None
