"""WebAuthn (passkey) ceremonies around py_webauthn: options, and response verification."""

# 1st party imports
from dataclasses import dataclass
from urllib.parse import urlsplit

# 3rd party imports
import webauthn
from webauthn.helpers import (
    bytes_to_base64url,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

# local imports
from mailalias.config import Settings

RP_NAME = "closetcompute mail"


class PasskeyError(ValueError):
    """The browser's response failed verification (or could not be parsed)."""


@dataclass(frozen=True)
class RelyingParty:
    """Where passkeys are valid: the app's host name and exact origin."""

    rp_id: str
    origin: str


@dataclass(frozen=True)
class VerifiedRegistration:
    """A new credential to store."""

    credential_id: str  # base64url
    public_key: bytes
    sign_count: int


def relying_party(settings: Settings) -> RelyingParty:
    """Derive the RP from APP_BASE_URL (app.closetcompute.online in prod, localhost in dev).

    Args:
        settings: Settings.
    Returns:
        RP id and origin.
    """
    parts = urlsplit(settings.app_base_url)
    return RelyingParty(
        rp_id=parts.hostname or "localhost", origin=f"{parts.scheme}://{parts.netloc}"
    )


def registration_options(
    rp: RelyingParty, user_id: bytes, username: str, existing: list[str]
) -> tuple[str, str]:
    """Options for navigator.credentials.create().

    Args:
        rp: Relying party.
        user_id: Stable opaque user handle.
        username: Shown by the authenticator.
        existing: Already registered credential ids (base64url), excluded.
    Returns:
        (options JSON for the browser, challenge as base64url to keep in the session).
    """
    options = webauthn.generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=RP_NAME,
        user_id=user_id,
        user_name=username,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(cid)) for cid in existing
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return webauthn.options_to_json(options), bytes_to_base64url(options.challenge)


def verify_registration(
    rp: RelyingParty, response_json: str, challenge: str
) -> VerifiedRegistration:
    """Check an attestation response against the issued challenge.

    Args:
        rp: Relying party.
        response_json: PublicKeyCredential JSON from the browser.
        challenge: Challenge from the session (base64url).
    Returns:
        The credential to store. Raises PasskeyError.
    """
    try:
        verified = webauthn.verify_registration_response(
            credential=parse_registration_credential_json(response_json),
            expected_challenge=webauthn.base64url_to_bytes(challenge),
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise PasskeyError(str(exc)) from exc
    return VerifiedRegistration(
        bytes_to_base64url(verified.credential_id),
        verified.credential_public_key,
        verified.sign_count,
    )


def authentication_options(rp: RelyingParty, allowed: list[str]) -> tuple[str, str]:
    """Options for navigator.credentials.get() limited to the user's passkeys.

    Args:
        rp: Relying party.
        allowed: The user's credential ids (base64url).
    Returns:
        (options JSON, challenge base64url).
    """
    options = webauthn.generate_authentication_options(
        rp_id=rp.rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(cid)) for cid in allowed
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return webauthn.options_to_json(options), bytes_to_base64url(options.challenge)


def credential_id_of(response_json: str) -> str:
    """The credential id a browser assertion claims to use.

    Args:
        response_json: PublicKeyCredential JSON.
    Returns:
        base64url credential id. Raises PasskeyError if unparsable.
    """
    try:
        return parse_authentication_credential_json(response_json).id
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise PasskeyError("unreadable passkey response") from exc


def verify_authentication(
    rp: RelyingParty, response_json: str, challenge: str, public_key: bytes, sign_count: int
) -> int:
    """Check an assertion signature against the stored key.

    Args:
        rp: Relying party.
        response_json: PublicKeyCredential JSON.
        challenge: Challenge from the session (base64url).
        public_key: Stored public key.
        sign_count: Stored signature counter.
    Returns:
        The new signature counter. Raises PasskeyError.
    """
    try:
        verified = webauthn.verify_authentication_response(
            credential=parse_authentication_credential_json(response_json),
            expected_challenge=webauthn.base64url_to_bytes(challenge),
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise PasskeyError(str(exc)) from exc
    return verified.new_sign_count
