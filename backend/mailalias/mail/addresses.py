"""Address normalisation and naming rules for aliases, usernames and reply tokens."""

# 1st party imports
import base64
import re
import secrets
from functools import lru_cache
from importlib import resources

LOCAL_PART_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
USERNAME_RE = re.compile(r"^[a-z0-9-]{3,30}$")
TOKEN_RE = re.compile(r"^[a-z2-7]{16}$")

# Labels that cannot be usernames because they would collide with infrastructure subdomains.
RESERVED_LABELS = frozenset(
    {"rp", "send", "rsend", "app", "www", "mail", "admin", "api", "dmarc", "bounce"}
)


def normalize(address: str) -> str:
    """Canonical form of an email address for comparison and storage.

    Args:
        address: Raw address.
    Returns:
        The stripped, lowercased address.
    """
    return address.strip().lower()


def split_address(address: str) -> tuple[str, str]:
    """Split an address into local part and domain at the last "@".

    Args:
        address: Address (normalised or not).
    Returns:
        (local, domain), both normalised. Raises ValueError if malformed.
    """
    local, sep, domain = normalize(address).rpartition("@")
    if not sep or not local or not domain:
        raise ValueError("malformed address")
    return local, domain


@lru_cache
def reserved_local_parts() -> frozenset[str]:
    """Load reserved local parts from data/reserved_locals.txt.

    Returns:
        The set of reserved local parts.
    """
    text = resources.files("mailalias.data").joinpath("reserved_locals.txt").read_text()
    return frozenset(
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    )


def is_valid_local_part(local: str) -> bool:
    """Whether a user-chosen alias local part is syntactically allowed.

    Args:
        local: Candidate local part (already lowercased).
    Returns:
        True if it matches the pattern and has no consecutive dots or trailing dot.
    """
    return bool(LOCAL_PART_RE.fullmatch(local)) and ".." not in local and not local.endswith(".")


def is_reserved_local_part(local: str) -> bool:
    """Whether a local part is reserved for role/system addresses.

    Args:
        local: Local part (lowercased).
    Returns:
        True if reserved.
    """
    return local in reserved_local_parts()


def is_valid_username(username: str) -> bool:
    """Whether a username is allowed (it also becomes a personal subdomain label).

    Args:
        username: Candidate username (lowercased).
    Returns:
        True if it matches the pattern, does not start/end with "-", and is not reserved.
    """
    return (
        bool(USERNAME_RE.fullmatch(username))
        and not username.startswith("-")
        and not username.endswith("-")
        and username not in RESERVED_LABELS
    )


def new_reply_token() -> str:
    """Generate an opaque reverse-alias token.

    Returns:
        16 lowercase base32 characters (80 bits of randomness).
    """
    return base64.b32encode(secrets.token_bytes(10)).decode().lower()


def is_service_domain(domain: str, alias_domain: str) -> bool:
    """Whether a domain belongs to this service (the alias domain or any subdomain of it).

    Args:
        domain: Domain to test.
        alias_domain: Settings.alias_domain.
    Returns:
        True for the apex, rp., personal subdomains, etc.
    """
    domain, alias_domain = normalize(domain).rstrip("."), normalize(alias_domain)
    return domain == alias_domain or domain.endswith("." + alias_domain)
