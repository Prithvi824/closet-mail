"""Tests for signed one-click action tokens."""

# 1st party imports
import time

# 3rd party imports
import pytest

# local imports
from mailalias.security.signing import InvalidActionToken, load_action, sign_action


def test_sign_and_load_round_trip() -> None:
    """A freshly signed payload loads back unchanged.

    Returns:
        None.
    """
    payload = {"a": "block_contact", "id": "c1", "uid": "u1"}
    assert load_action(sign_action(payload)) == payload


def test_tampered_token_is_rejected() -> None:
    """Changing any character of the token invalidates it.

    Returns:
        None.
    """
    token = sign_action({"a": "disable_alias", "id": "a1", "uid": "u1"})
    # Change the first payload character: unlike the last base64 char, all its bits are used.
    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    with pytest.raises(InvalidActionToken):
        load_action(tampered)


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token older than max_age_days fails to load.

    Args:
        monkeypatch: Used to sign the token as if 2 days ago.
    Returns:
        None.
    """
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now - 2 * 86_400)
    token = sign_action({"a": "block_contact", "id": "c1", "uid": "u1"})
    monkeypatch.setattr(time, "time", lambda: now)
    with pytest.raises(InvalidActionToken):
        load_action(token, max_age_days=1)
