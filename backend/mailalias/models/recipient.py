"""Recipients: the real mailboxes a user's aliases forward to."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey
from mailalias.security.crypto import EncryptedString


class Recipient(UUIDPrimaryKey, Timestamps, Base):
    """A verified-or-pending destination mailbox, optionally with a PGP key."""

    __tablename__ = "recipients"
    __table_args__ = (UniqueConstraint("user_id", "email_hash", name="uq_recipients_user_email"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(EncryptedString())
    email_hash: Mapped[str] = mapped_column(String(64), index=True)
    verified_at: Mapped[datetime | None]
    verify_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    verify_sent_at: Mapped[datetime | None]
    pgp_public_key: Mapped[str | None] = mapped_column(Text)
    pgp_fingerprint: Mapped[str | None] = mapped_column(String(64))
    pgp_protect_subject: Mapped[bool] = mapped_column(default=False)
    disabled_at: Mapped[datetime | None]
    consecutive_hard_bounces: Mapped[int] = mapped_column(default=0)

    @property
    def is_usable(self) -> bool:
        """Whether mail may be forwarded here.

        Returns:
            True if verified and not disabled.
        """
        return self.verified_at is not None and self.disabled_at is None
