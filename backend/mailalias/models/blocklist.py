"""Per-user blocklist of sender addresses and domains."""

# 1st party imports
import uuid
from enum import StrEnum

# 3rd party imports
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from mailalias.security.crypto import EncryptedString


class BlockKind(StrEnum):
    """What a blocklist pattern matches."""

    ADDRESS = "address"
    DOMAIN = "domain"


class BlocklistEntry(UUIDPrimaryKey, Timestamps, Base):
    """A blocked sender address or domain, matched by `pattern_hash`."""

    __tablename__ = "blocklist"
    __table_args__ = (
        UniqueConstraint("user_id", "pattern_hash", name="uq_blocklist_user_pattern"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    pattern_hash: Mapped[str] = mapped_column(String(64), index=True)
    pattern: Mapped[str] = mapped_column(EncryptedString())
    kind: Mapped[BlockKind] = mapped_column(pg_enum(BlockKind, "block_kind"))
