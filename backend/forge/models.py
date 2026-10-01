from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Input):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128, repr=False)


class AppInput(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)


class Selection(Input):
    revision_id: UUID
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,80}$")


class RunInput(Input):
    prompt: str = Field(min_length=1, max_length=12000)
    base_revision: UUID | None = None
    selection: Selection | None = None


class FieldDefinition(Input):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "number", "boolean", "date"] = "text"
    required: bool = False


class EntityDefinition(Input):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    label: str = Field(min_length=1, max_length=80)
    fields: list[FieldDefinition] = Field(min_length=1, max_length=12)


class AppDefinition(Input):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    accent: str = Field(default="#4f46e5", pattern=r"^#[0-9a-fA-F]{6}$")
    entities: list[EntityDefinition] = Field(min_length=1, max_length=6)
