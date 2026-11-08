"""Shared strict Pydantic schema bases."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, RootModel
from pydantic.fields import FieldInfo

RootValueT = TypeVar("RootValueT")
SchemaItemT = TypeVar("SchemaItemT")
SchemaKeyT = TypeVar("SchemaKeyT")
SchemaValueT = TypeVar("SchemaValueT")


class StrictSchemaModel(BaseModel):
    """Provide the backend-wide default for named-field schemas."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        use_enum_values=True,
        validate_default=True,
    )


class StrictRootSchemaModel(RootModel[RootValueT]):
    """Provide the backend-wide default for root-value schemas."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        use_enum_values=True,
        validate_default=True,
    )


def exclude_none_field() -> FieldInfo:
    """Exclude a field from serialization only when its value is None.

    Returns:
        Pydantic field metadata with a None-only exclusion predicate.
    """

    # Broad type justified: Pydantic passes arbitrary validated field values.
    def is_none(value: object) -> bool:
        """Return whether none.

        Args:
            value: Value being processed.

        Returns:
            Whether none.
        """
        return value is None

    return Field(exclude_if=is_none)


def schema_list_default() -> list[SchemaItemT]:
    """Return an explicit empty list default for a Pydantic model field.

    Returns:
        New typed list instance for one schema field.
    """

    return []


def schema_dict_default() -> dict[SchemaKeyT, SchemaValueT]:
    """Return an explicit empty mapping default for a Pydantic model field.

    Returns:
        New typed dictionary instance for one schema field.
    """

    return {}
