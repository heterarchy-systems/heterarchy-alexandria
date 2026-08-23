"""Strict Pydantic validation for values already decoded from JSON."""

from __future__ import annotations

from pydantic import BaseModel

from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue


def model_validate_json_value[SchemaT: BaseModel](
    schema_type: type[SchemaT],
    value: JSONValue,
) -> SchemaT:
    """Validate a decoded JSON value using Pydantic's strict JSON semantics.

    Args:
        schema_type: Pydantic schema class for the decoded value.
        value: JSON-compatible value already decoded by a transport.

    Returns:
        Strictly validated schema instance.
    """

    return schema_type.model_validate_json(dumps_json(value))
