"""Shared strict Pydantic schema bases."""

from __future__ import annotations

from typing import TypeVar

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, RootModel
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonDict

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


def described_field(
    description: str,
    ge: int | float | None = None,
    gt: int | float | None = None,
    le: int | float | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    validation_alias: str | AliasPath | AliasChoices | None = None,
    repr: bool = True,
    json_schema_extra: JsonDict | None = None,
) -> FieldInfo:
    """Create constrained field metadata with a mandatory description.

    Args:
        description: Non-empty public schema description.
        ge: Optional inclusive numeric lower bound.
        gt: Optional exclusive numeric lower bound.
        le: Optional inclusive numeric upper bound.
        min_length: Optional minimum collection or string length.
        max_length: Optional maximum collection or string length.
        validation_alias: Optional accepted external field alias.
        repr: Whether the field appears in model representations.
        json_schema_extra: Optional explicit JSON Schema metadata.

    Returns:
        Pydantic field metadata for an annotated schema field.
    """

    normalized_description = description.strip()
    if not normalized_description:
        raise ValueError("Pydantic field description must not be blank")
    return Field(
        description=normalized_description,
        ge=ge,
        gt=gt,
        le=le,
        min_length=min_length,
        max_length=max_length,
        validation_alias=validation_alias,
        repr=repr,
        json_schema_extra=json_schema_extra,
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
