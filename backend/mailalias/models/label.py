"""User-defined labels for organising aliases."""

# 1st party imports
import uuid

# 3rd party imports
from sqlalchemy import Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey

alias_labels = Table(
    "alias_labels",
    Base.metadata,
    Column("alias_id", ForeignKey("aliases.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Label(UUIDPrimaryKey, Timestamps, Base):
    """A named, coloured tag owned by one user."""

    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_labels_user_name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(7), default="#64748b")
