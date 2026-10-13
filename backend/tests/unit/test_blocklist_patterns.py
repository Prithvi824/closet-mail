"""Tests for blocklist pattern parsing and the hashes checked at forward time."""

# 3rd party imports
import pytest

# local imports
from mailalias.api.errors import ValidationFailed
from mailalias.models import BlockKind
from mailalias.security.crypto import lookup_hash
from mailalias.services.blocklist import candidate_hashes, parse_pattern


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (" Spam@Example.COM ", ("spam@example.com", BlockKind.ADDRESS)),
        ("example.com", ("example.com", BlockKind.DOMAIN)),
        ("@Mail.Example.org", ("mail.example.org", BlockKind.DOMAIN)),
    ],
)
def test_valid_patterns(pattern: str, expected: tuple[str, BlockKind]) -> None:
    """Addresses and domains are normalised and classified."""
    assert parse_pattern(pattern) == expected


@pytest.mark.parametrize("pattern", ["example", "a b@example.com", "@", "x@-bad-.com", "com"])
def test_invalid_patterns(pattern: str) -> None:
    """Anything that is neither an address nor a domain is refused."""
    with pytest.raises(ValidationFailed):
        parse_pattern(pattern)


def test_candidate_hashes_cover_address_and_parent_domains() -> None:
    """A sender matches its exact address, its domain and each parent domain (not the TLD)."""
    hashes = candidate_hashes("Bob@News.Example.com")
    expected = ["bob@news.example.com", "news.example.com", "example.com"]
    assert hashes == [lookup_hash(value) for value in expected]
    assert candidate_hashes("") == []
