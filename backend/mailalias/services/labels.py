"""User-owned labels for organising aliases."""

# 1st party imports
import uuid

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound
from mailalias.models import Label, User


class LabelService:
    """Label CRUD scoped to one owner."""

    def __init__(self, db: AsyncSession) -> None:
        """Build the service.

        Args:
            db: Database session.
        Returns:
            None.
        """
        self.db = db

    async def list_for(self, user: User) -> list[Label]:
        """All labels of a user, by name.

        Args:
            user: Owner.
        Returns:
            Labels.
        """
        query = select(Label).where(Label.user_id == user.id).order_by(Label.name)
        return list(await self.db.scalars(query))

    async def get_owned(self, user: User, label_id: uuid.UUID) -> Label:
        """Fetch a label owned by the user.

        Args:
            user: Owner.
            label_id: Label id.
        Returns:
            The label. Raises NotFound.
        """
        label = await self.db.get(Label, label_id)
        if label is None or label.user_id != user.id:
            raise NotFound("Label not found")
        return label

    async def _save(self, label: Label) -> Label:
        """Flush inside a savepoint, mapping duplicate names to Conflict.

        Args:
            label: New or changed label.
        Returns:
            The label.
        """
        try:
            async with self.db.begin_nested():
                self.db.add(label)
                await self.db.flush()
        except IntegrityError as exc:
            raise Conflict("A label with this name already exists") from exc
        return label

    async def create(self, user: User, name: str, color: str | None) -> Label:
        """Create a label.

        Args:
            user: Owner.
            name: Unique (per user) name.
            color: Hex colour, or None for the default.
        Returns:
            The label.
        """
        label = Label(user_id=user.id, name=name.strip())
        if color:
            label.color = color
        return await self._save(label)

    async def update(
        self, user: User, label_id: uuid.UUID, name: str | None, color: str | None
    ) -> Label:
        """Rename or recolour a label.

        Args:
            user: Owner.
            label_id: Label id.
            name: New name or None.
            color: New colour or None.
        Returns:
            The label.
        """
        label = await self.get_owned(user, label_id)
        if name is not None:
            label.name = name.strip()
        if color is not None:
            label.color = color
        return await self._save(label)

    async def delete(self, user: User, label_id: uuid.UUID) -> None:
        """Delete a label (alias links cascade).

        Args:
            user: Owner.
            label_id: Label id.
        Returns:
            None.
        """
        await self.db.delete(await self.get_owned(user, label_id))
        await self.db.flush()
