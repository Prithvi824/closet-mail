"""Tests for address normalisation and naming rules."""

# 3rd party imports
import pytest

# local imports
from mailalias.mail import addresses


def test_normalize_and_split() -> None:
    """Whitespace and case are normalised; split uses the last "@"."""
    assert addresses.normalize("  Foo.Bar@Example.COM ") == "foo.bar@example.com"
    assert addresses.split_address('"a@b"@Example.com') == ('"a@b"', "example.com")
    for bad in ("", "nodomain@", "@nolocal", "plain"):
        with pytest.raises(ValueError):
            addresses.split_address(bad)


@pytest.mark.parametrize(
    ("local", "valid"),
    [
        ("shop", True),
        ("shop.fox42", True),
        ("a-b_c", True),
        ("0abc", True),
        ("a" * 64, True),
        ("a" * 65, False),
        (".shop", False),
        ("-shop", False),
        ("sh..op", False),
        ("shop.", False),
        ("Shop", False),
        ("sh+op", False),
        ("", False),
    ],
)
def test_local_part_rules(local: str, valid: bool) -> None:
    """Pattern, no consecutive or trailing dots."""
    assert addresses.is_valid_local_part(local) is valid


def test_reserved_local_parts() -> None:
    """Role addresses from data/reserved_locals.txt are reserved."""
    for local in ("postmaster", "abuse", "mailer-daemon", "noreply"):
        assert addresses.is_reserved_local_part(local)
    assert not addresses.is_reserved_local_part("shop")


@pytest.mark.parametrize(
    ("username", "valid"),
    [
        ("alice", True),
        ("al-ice9", True),
        ("ab", False),
        ("a" * 31, False),
        ("-alice", False),
        ("alice-", False),
        ("al.ice", False),
        ("rp", False),
        ("admin", False),
        ("Alice", False),
    ],
)
def test_username_rules(username: str, valid: bool) -> None:
    """Pattern, hyphen placement and reserved labels."""
    assert addresses.is_valid_username(username) is valid


def test_reply_token_format() -> None:
    """Tokens are 16 lowercase base32 chars and unique."""
    tokens = {addresses.new_reply_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(addresses.TOKEN_RE.fullmatch(token) for token in tokens)
