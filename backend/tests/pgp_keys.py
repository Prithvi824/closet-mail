"""Generates throwaway PGP test keys (fast curve25519) in isolated keyrings."""

# 1st party imports
import tempfile
from dataclasses import dataclass

# 3rd party imports
import gnupg


@dataclass(frozen=True)
class PgpTestKey:
    """An exported test key pair."""

    public: str
    private: str
    fingerprint: str


def make_key(
    email: str, *, encrypt: bool = True, expire: str = "0", faked_time: str | None = None
) -> PgpTestKey:
    """Generate a key pair and export it.

    Args:
        email: User id email.
        encrypt: Add a cv25519 encryption subkey (False gives a sign-only key).
        expire: GnuPG Expire-Date ("0" = never).
        faked_time: Optional --faked-system-time value to create keys in the past.
    Returns:
        The exported keys.
    """
    with tempfile.TemporaryDirectory() as home:
        options = [f"--faked-system-time={faked_time}"] if faked_time else None
        gpg = gnupg.GPG(gnupghome=home, options=options)
        params = {
            "key_type": "EDDSA",
            "key_curve": "ed25519",
            "key_usage": "sign",
            "name_email": email,
            "expire_date": expire,
            "no_protection": True,
        }
        if encrypt:
            params |= {"subkey_type": "ECDH", "subkey_curve": "cv25519", "subkey_usage": "encrypt"}
        key = gpg.gen_key(gpg.gen_key_input(**params))
        assert key.fingerprint, key.stderr
        fingerprint = str(key.fingerprint)
        return PgpTestKey(
            public=str(gpg.export_keys(fingerprint)),
            private=str(gpg.export_keys(fingerprint, secret=True, expect_passphrase=False)),
            fingerprint=fingerprint,
        )
