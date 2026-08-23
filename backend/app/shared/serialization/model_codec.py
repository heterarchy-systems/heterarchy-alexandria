"""Pydantic model serialization helper module."""

from __future__ import annotations

from pydantic import BaseModel

from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONObject


def model_to_dict(model: BaseModel) -> JSONObject:
    """Convert a Pydantic model to a JSON-compatible dictionary.

    Args:
        model: See function signature.

    Returns:
        Return value.
    """
    return model.model_dump()


def schema_payload(
    schema: BaseModel,
    by_alias: bool = False,
    exclude_none: bool = False,
    exclude_unset: bool = False,
) -> JSONObject:
    """Serialize one Pydantic schema into a JSON-compatible object.

    Args:
        schema: Pydantic schema to serialize at an adapter boundary.
        by_alias: Whether serialized field aliases should be used.
        exclude_none: Whether nullable fields with ``None`` values are omitted.
        exclude_unset: Whether fields absent from the request are omitted.

    Returns:
        JSON-compatible object payload.
    """
    payload = schema.model_dump(
        mode="json",
        by_alias=by_alias,
        exclude_none=exclude_none,
        exclude_unset=exclude_unset,
    )
    return payload


def dumps_model(model: BaseModel) -> bytes:
    """Serialize a Pydantic model to orjson bytes.

    Args:
        model: See function signature.

    Returns:
        Return value.
    """
    return dumps_json(model_to_dict(model))
