"""User accounts: creation, authentication, passwords, TOTP and preferences."""

# 1st party imports
import hashlib
import secrets
import uuid
from datetime import UTC, datetime

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from mailalias.mail.addresses import is_valid_username, normalize
from mailalias.models import Recipient, User, UserRole
from mailalias.security import totp
from mailalias.security.crypto import lookup_hash
from mailalias.security.passwords import hash_password, needs_rehash, verify_password
from mailalias.services import audit
from mailalias.services.system_mail import SystemMailService

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
RESET_TTL_SECONDS = 3600
_RESET_KEY = "pwreset:{digest}"
_TOTP_USED_KEY = "totp:used:{user_id}:{code}"
_MFA_FAIL_KEY = "mfa:fail:{user_id}"
# Wrong second-factor codes allowed per user before MFA is locked for the window.
MFA_MAX_FAILURES = 5
MFA_LOCK_SECONDS = 900
# Verified against when the username does not exist, so timing does not reveal accounts.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def token_digest(token: str) -> str:
    """Hash a one-time URL token for storage.

    Args:
        token: The plaintext token from a link.
    Returns:
        Its SHA-256 hex digest.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def check_password_policy(password: str) -> None:
    """Enforce password length rules.

    Args:
        password: Candidate password.
    Returns:
        None. Raises ValidationFailed if too short or too long.
    """
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValidationFailed(
            f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters",
            code="weak_password",
        )


class UserService:
    """Account operations shared by the API and the CLI."""

    def __init__(self, db: AsyncSession, redis: Redis | None = None) -> None:
        """Build the service.

        Args:
            db: Database session.
            redis: Redis client (needed for password reset and TOTP replay protection).
        Returns:
            None.
        """
        self.db = db
        self.redis = redis

    async def get_by_username(self, username: str) -> User | None:
        """Find a user by username.

        Args:
            username: Username (case-insensitive).
        Returns:
            The user or None.
        """
        return await self.db.scalar(select(User).where(User.username == username.strip().lower()))

    async def get_by_email(self, email: str) -> User | None:
        """Find a user by account email via its lookup hash.

        Args:
            email: Account email.
        Returns:
            The user or None.
        """
        return await self.db.scalar(select(User).where(User.email_hash == lookup_hash(email)))

    async def create_user(
        self, username: str, email: str, password: str, role: UserRole = UserRole.USER
    ) -> User:
        """Create a user plus a verified default recipient for the account email.

        Args:
            username: Desired username (becomes the personal subdomain label).
            email: Account email (already proven by invite or by the admin).
            password: Plaintext password.
            role: Account role.
        Returns:
            The new user (flushed, not committed). Raises ValidationFailed/Conflict.
        """
        username = username.strip().lower()
        email = normalize(email)
        if not is_valid_username(username):
            raise ValidationFailed("Username is not allowed", code="invalid_username")
        check_password_policy(password)
        user = User(
            username=username,
            email=email,
            email_hash=lookup_hash(email),
            password_hash=hash_password(password),
            role=role,
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise Conflict("Username or email already in use") from exc
        recipient = Recipient(
            user_id=user.id, email=email, email_hash=lookup_hash(email), verified_at=_now()
        )
        self.db.add(recipient)
        await self.db.flush()
        user.default_recipient_id = recipient.id
        await self.db.flush()
        return user

    async def authenticate(self, username: str, password: str) -> User | None:
        """Verify credentials in roughly constant time.

        Args:
            username: Username.
            password: Plaintext password.
        Returns:
            The user if the password matches and the account is enabled, else None.
        """
        user = await self.get_by_username(username)
        if user is None:
            verify_password(_DUMMY_HASH, password)
            return None
        if not verify_password(user.password_hash, password) or user.disabled_at is not None:
            return None
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return user

    async def verify_second_factor(self, user: User, code: str) -> bool:
        """Accept a TOTP code (once per user and time step) or an unused backup code.

        Args:
            user: User with TOTP enabled.
            code: TOTP or backup code.
        Returns:
            True if accepted; a used backup code is removed from the user.
        """
        cleaned = code.replace(" ", "")
        if user.totp_secret and totp.verify_code(user.totp_secret, cleaned):
            if self.redis is None:
                return True
            # Reject replay of the same code within its validity window.
            key = _TOTP_USED_KEY.format(user_id=user.id, code=cleaned)
            return bool(await self.redis.set(key, "1", nx=True, ex=90))
        remaining = totp.consume_backup_code(list(user.backup_codes_hash or []), cleaned)
        if remaining is None:
            return False
        user.backup_codes_hash = remaining
        await audit.record(self.db, "mfa.backup_code_used", user_id=user.id)
        return True

    async def mfa_locked(self, user: User) -> bool:
        """Whether the user has hit the wrong-code limit for the current window.

        Args:
            user: The user.
        Returns:
            True while second-factor attempts are locked.
        """
        if self.redis is None:
            return False
        failures = await self.redis.get(_MFA_FAIL_KEY.format(user_id=user.id))
        return failures is not None and int(failures) >= MFA_MAX_FAILURES

    async def record_mfa_failure(self, user: User) -> None:
        """Count a wrong second-factor code; the counter expires after the lock window.

        Args:
            user: The user.
        Returns:
            None.
        """
        if self.redis is None:
            return
        key = _MFA_FAIL_KEY.format(user_id=user.id)
        if await self.redis.incr(key) == 1:
            await self.redis.expire(key, MFA_LOCK_SECONDS)

    async def begin_totp_setup(self, user: User) -> str:
        """Store a fresh (not yet enabled) TOTP secret.

        Args:
            user: The user.
        Returns:
            The otpauth:// provisioning URI.
        """
        if user.totp_enabled:
            raise Conflict("Two-factor authentication is already enabled")
        user.totp_secret = totp.new_secret()
        await self.db.flush()
        return totp.provisioning_uri(user.totp_secret, user.username)

    async def enable_totp(self, user: User, code: str) -> list[str]:
        """Confirm the pending secret with a code and issue backup codes.

        Args:
            user: The user.
            code: Code from the authenticator app.
        Returns:
            The plaintext backup codes (shown once).
        """
        if user.totp_enabled or not user.totp_secret:
            raise Conflict("Start two-factor setup first")
        if not totp.verify_code(user.totp_secret, code):
            raise ValidationFailed("Invalid code", code="invalid_code")
        codes, hashes = totp.new_backup_codes()
        user.totp_enabled = True
        user.backup_codes_hash = hashes
        await audit.record(self.db, "mfa.totp_enabled", user_id=user.id)
        await self.db.flush()
        return codes

    async def disable_totp(self, user: User, password: str) -> None:
        """Turn off TOTP after re-checking the password.

        Args:
            user: The user.
            password: Current password.
        Returns:
            None. Raises Unauthorized on a wrong password.
        """
        if not verify_password(user.password_hash, password):
            raise Unauthorized("Wrong password", code="wrong_password")
        user.totp_enabled = False
        user.totp_secret = None
        user.backup_codes_hash = []
        await audit.record(self.db, "mfa.totp_disabled", user_id=user.id)
        await self.db.flush()

    async def request_password_reset(self, email: str, mail: SystemMailService) -> None:
        """Email a reset link if the account exists; silent otherwise.

        Args:
            email: Account email.
            mail: System mail service.
        Returns:
            None.
        """
        assert self.redis is not None
        user = await self.get_by_email(email)
        if user is None or user.disabled_at is not None:
            return
        token = secrets.token_urlsafe(32)
        await self.redis.set(
            _RESET_KEY.format(digest=token_digest(token)), str(user.id), ex=RESET_TTL_SECONDS
        )
        await audit.record(self.db, "password.reset_requested", user_id=user.id)
        await mail.send("password_reset", user.email, link=mail.link(f"/reset/{token}"))

    async def confirm_password_reset(self, token: str, password: str) -> User:
        """Set a new password from a reset token (single use).

        Args:
            token: Token from the reset link.
            password: New password.
        Returns:
            The user. Raises NotFound for invalid/expired tokens.
        """
        assert self.redis is not None
        check_password_policy(password)
        user_id = await self.redis.getdel(_RESET_KEY.format(digest=token_digest(token)))
        user = await self.db.get(User, uuid.UUID(str(user_id))) if user_id else None
        if user is None:
            raise NotFound("Reset link is invalid or expired", code="invalid_token")
        user.password_hash = hash_password(password)
        await audit.record(self.db, "password.reset", user_id=user.id)
        await self.db.flush()
        return user


def _now() -> datetime:
    """Current UTC time.

    Returns:
        Timezone-aware now.
    """
    return datetime.now(UTC)
