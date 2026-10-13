"""Request/response models for labels."""

# 1st party imports
import uuid

# 3rd party imports
from pydantic import BaseModel, ConfigDict, Field

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class LabelCreate(BaseModel):
    """New label."""

    name: str = Field(min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class LabelUpdate(BaseModel):
    """Rename or recolour."""

    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class LabelResponse(BaseModel):
    """A label."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
