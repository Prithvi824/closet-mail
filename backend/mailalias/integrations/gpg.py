"""GnuPG helpers: inspect uploaded public keys and encrypt to them (isolated keyrings)."""

# 1st party imports
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

# 3rd party imports
import gnupg

PRIVATE_KEY_MARKER = "PRIVATE KEY BLOCK"
MAX_KEY_BYTES = 64 * 1024


class InvalidPgpKey(ValueError):
    """The uploaded text is not a single usable public key."""


@dataclass(frozen=True)
class KeyInfo:
    """Facts about an uploaded public key."""

    fingerprint: str
    can_encrypt: bool
    expires_at: datetime | None


def _import(gpg: gnupg.GPG, armored: str) -> str:
    """Import exactly one public key into a throwaway keyring.

    Args:
        gpg: GPG bound to a temporary home.
        armored: ASCII-armored public key.
    Returns:
        The key fingerprint. Raises InvalidPgpKey.
    """
    if len(armored.encode()) > MAX_KEY_BYTES:
        raise InvalidPgpKey("key is too large")
    if PRIVATE_KEY_MARKER in armored:
        raise InvalidPgpKey("that is a private key; upload the public key only")
    result = gpg.import_keys(armored)
    fingerprints = sorted(set(result.fingerprints or []))
    if len(fingerprints) != 1:
        raise InvalidPgpKey("expected exactly one public key")
    return str(fingerprints[0])


def inspect_key(armored: str) -> KeyInfo:
    """Parse a public key and report its fingerprint, encryption capability and expiry.

    Args:
        armored: ASCII-armored public key.
    Returns:
        KeyInfo. Raises InvalidPgpKey if unparsable or not exactly one key.
    """
    with tempfile.TemporaryDirectory() as home:
        gpg = gnupg.GPG(gnupghome=home)
        fingerprint = _import(gpg, armored)
        keys = [k for k in gpg.list_keys() if k.get("fingerprint") == fingerprint]
        if not keys:
            raise InvalidPgpKey("key could not be read")
        key = keys[0]
        expires = key.get("expires")
        # Uppercase capability letters describe the whole key including usable subkeys.
        return KeyInfo(
            fingerprint=fingerprint,
            can_encrypt="E" in (key.get("cap") or ""),
            expires_at=datetime.fromtimestamp(int(expires), UTC) if expires else None,
        )


def encrypt_many(items: list[bytes], armored_key: str) -> list[bytes]:
    """Encrypt several byte strings to one public key, importing the key once.

    Args:
        items: Plaintexts.
        armored_key: Recipient's ASCII-armored public key.
    Returns:
        Armored PGP messages, in order. Raises RuntimeError if gpg fails.
    """
    with tempfile.TemporaryDirectory() as home:
        gpg = gnupg.GPG(gnupghome=home)
        fingerprint = _import(gpg, armored_key)
        encrypted = []
        for data in items:
            result = gpg.encrypt(data, fingerprint, armor=True, always_trust=True)
            if not result.ok:
                raise RuntimeError(f"gpg encryption failed: {result.status}")
            encrypted.append(bytes(result.data))
        return encrypted


def encrypt(data: bytes, armored_key: str) -> bytes:
    """Encrypt bytes to a public key, producing ASCII armor.

    Args:
        data: Plaintext bytes.
        armored_key: Recipient's ASCII-armored public key.
    Returns:
        The armored PGP message as bytes. Raises RuntimeError if gpg fails.
    """
    return encrypt_many([data], armored_key)[0]
