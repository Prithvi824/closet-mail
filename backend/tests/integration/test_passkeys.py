"""Passkeys: registration and login ceremonies (signature checks mocked), MFA gating."""

# 1st party imports
from typing import Any

# 3rd party imports
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.security import webauthn as passkey
from mailalias.services.users import UserService

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
PASSWORD = "passkey-password-1"
CREDENTIAL_ID = "Y3JlZC0x"  # base64url("cred-1")
BROWSER_RESPONSE: dict[str, Any] = {
    "id": CREDENTIAL_ID,
    "rawId": CREDENTIAL_ID,
    "type": "public-key",
    "response": {"clientDataJSON": "e30", "authenticatorData": "AA", "signature": "AA"},
}


@pytest.fixture
def fake_verifier(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the cryptographic checks; record the challenges they were given.

    Args:
        monkeypatch: Pytest monkeypatch.
    Returns:
        State dict: {"challenges": [...], "fail": bool}.
    """
    state: dict[str, Any] = {"challenges": [], "fail": False}

    def verify_registration(
        rp: passkey.RelyingParty, response_json: str, challenge: str
    ) -> passkey.VerifiedRegistration:
        state["challenges"].append(challenge)
        return passkey.VerifiedRegistration(CREDENTIAL_ID, b"public-key", 0)

    def verify_authentication(
        rp: passkey.RelyingParty,
        response_json: str,
        challenge: str,
        public_key: bytes,
        sign_count: int,
    ) -> int:
        state["challenges"].append(challenge)
        if state["fail"]:
            raise passkey.PasskeyError("bad signature")
        assert public_key == b"public-key"
        return sign_count + 1

    monkeypatch.setattr(passkey, "verify_registration", verify_registration)
    monkeypatch.setattr(passkey, "verify_authentication", verify_authentication)
    return state


async def _login(client: httpx.AsyncClient) -> dict[str, Any]:
    """Password step.

    Args:
        client: Client.
    Returns:
        Login response body.
    """
    response = await client.post(
        "/api/v1/auth/login", json={"username": "pia", "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


async def _register(client: httpx.AsyncClient) -> dict[str, Any]:
    """Run the registration ceremony.

    Args:
        client: Signed-in client.
    Returns:
        The begin options.
    """
    begin = await client.post("/api/v1/me/webauthn/register/begin")
    assert begin.status_code == 200
    finish = await client.post(
        "/api/v1/me/webauthn/register/finish",
        json={"name": "Laptop", "credential": BROWSER_RESPONSE},
    )
    assert finish.status_code == 201, finish.text
    return begin.json()["options"]


async def test_registration_then_passkey_login(
    client: httpx.AsyncClient, session: AsyncSession, fake_verifier: dict[str, Any]
) -> None:
    """Options carry our RP; after registering, login needs the passkey and it completes MFA."""
    await UserService(session).create_user("pia", "pia@example.com", PASSWORD)
    await session.commit()
    assert (await _login(client))["mfa_required"] is False
    options = await _register(client)
    assert options["rp"]["id"] == "testserver" and options["user"]["name"] == "pia"
    assert fake_verifier["challenges"] == [options["challenge"]]
    (listed,) = (await client.get("/api/v1/me/webauthn")).json()
    assert listed["name"] == "Laptop"

    await client.post("/api/v1/auth/logout")
    login = await _login(client)
    assert login == {"mfa_required": True, "mfa_methods": ["webauthn"]}
    assert (await client.get("/api/v1/me")).status_code == 401
    begin = await client.post("/api/v1/auth/webauthn/begin")
    allowed = [item["id"] for item in begin.json()["options"]["allowCredentials"]]
    assert allowed == [CREDENTIAL_ID]
    finish = await client.post(
        "/api/v1/auth/webauthn/finish", json={"credential": BROWSER_RESPONSE}
    )
    assert finish.status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 200


async def test_failed_and_replayed_assertions_are_rejected(
    client: httpx.AsyncClient, session: AsyncSession, fake_verifier: dict[str, Any]
) -> None:
    """A bad signature fails; the challenge is single-use; unknown credentials fail."""
    await UserService(session).create_user("pia", "pia@example.com", PASSWORD)
    await session.commit()
    await _login(client)
    await _register(client)
    await client.post("/api/v1/auth/logout")
    await _login(client)

    await client.post("/api/v1/auth/webauthn/begin")
    fake_verifier["fail"] = True
    bad = await client.post("/api/v1/auth/webauthn/finish", json={"credential": BROWSER_RESPONSE})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_passkey"
    fake_verifier["fail"] = False
    replay = await client.post(
        "/api/v1/auth/webauthn/finish", json={"credential": BROWSER_RESPONSE}
    )
    assert replay.status_code == 422  # challenge already used
    await client.post("/api/v1/auth/webauthn/begin")
    stranger = {**BROWSER_RESPONSE, "id": "b3RoZXI", "rawId": "b3RoZXI"}
    unknown = await client.post("/api/v1/auth/webauthn/finish", json={"credential": stranger})
    assert unknown.status_code == 401
    await client.post("/api/v1/auth/webauthn/begin")
    garbage = await client.post("/api/v1/auth/webauthn/finish", json={"credential": {"id": 1}})
    assert garbage.status_code == 401
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_delete_passkey_removes_the_second_factor(
    client: httpx.AsyncClient, session: AsyncSession, fake_verifier: dict[str, Any]
) -> None:
    """Without passkeys (and no TOTP) login is single-factor again."""
    await UserService(session).create_user("pia", "pia@example.com", PASSWORD)
    await session.commit()
    await _login(client)
    await _register(client)
    (listed,) = (await client.get("/api/v1/me/webauthn")).json()
    assert (await client.delete(f"/api/v1/me/webauthn/{listed['id']}")).status_code == 204
    await client.post("/api/v1/auth/logout")
    assert (await _login(client))["mfa_required"] is False


def test_relying_party_from_base_url() -> None:
    """RP id is the host; origin keeps scheme and port."""
    from mailalias.config import get_settings

    prod = get_settings().model_copy(update={"app_base_url": "https://app.closetcompute.online/"})
    dev = get_settings().model_copy(update={"app_base_url": "http://localhost:5173"})
    assert passkey.relying_party(prod) == passkey.RelyingParty(
        "app.closetcompute.online", "https://app.closetcompute.online"
    )
    assert passkey.relying_party(dev) == passkey.RelyingParty("localhost", "http://localhost:5173")
