"""Strict JSON-mode validation for FastAPI request bodies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from json import dumps

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BeforeValidator, TypeAdapter, ValidationError

from app.shared.schemas.common_schemas import StrictRootSchemaModel, StrictSchemaModel
from app.shared.types.extra_types import JSONValue

_JSON_VALUE_ADAPTER = TypeAdapter(JSONValue)


def model_validate_json_body[SchemaT: StrictSchemaModel](
    schema_type: type[SchemaT],
) -> Callable[[Request], Awaitable[SchemaT]]:
    """Build a FastAPI dependency that preserves Pydantic JSON-mode semantics.

    Args:
        schema_type: Strict schema class used to validate the raw request body.

    Returns:
        Async FastAPI dependency returning a validated schema instance.
    """

    async def dependency(request: Request) -> SchemaT:
        """Execute dependency.

        Args:
            request: Validated request for this operation.

        Returns:
            SchemaT result produced by dependency.
        """
        try:
            return schema_type.model_validate_json(await request.body())
        except ValidationError as exc:
            errors = exc.errors()
            for error in errors:
                error["loc"] = ("body", *error["loc"])
            raise RequestValidationError(errors) from exc

    return dependency


def json_mode_body[SchemaT: StrictSchemaModel | StrictRootSchemaModel[object]](
    schema_type: type[SchemaT],
) -> BeforeValidator:
    """Validate a decoded FastAPI body with Pydantic JSON-mode semantics.

    FastAPI only publishes a request body schema when a route parameter is a
    model body.  This metadata keeps that public contract while round-tripping
    the framework-decoded value through the same JSON mode used by the existing
    raw-body dependency.  The recursive JSON adapter is the only intentionally
    opaque framework boundary; the value is narrowed before serialization and
    schema validation.

    Args:
        schema_type: Strict named or root schema used for the request body.

    Returns:
        Pydantic before-validator metadata for an Annotated body parameter.
    """

    def validate(value: object) -> SchemaT:
        """Validate one framework-decoded request body."""
        if isinstance(value, schema_type):
            return value
        json_value = _JSON_VALUE_ADAPTER.validate_python(value)
        try:
            encoded = dumps(json_value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "request body must contain JSON-compatible values"
            ) from exc
        return schema_type.model_validate_json(encoded)

    return BeforeValidator(validate)


def model_validate_optional_json_body[SchemaT: StrictSchemaModel](
    schema_type: type[SchemaT],
) -> Callable[[Request], Awaitable[SchemaT | None]]:
    """Build a strict JSON dependency for an optional request body.

    An absent/empty body and the JSON literal ``null`` preserve the existing
    optional-body contract. Any non-null JSON payload is validated with the
    same strict JSON semantics as required request bodies.

    Args:
        schema_type: Strict schema class used for a non-null request body.

    Returns:
        Async dependency returning a validated schema or None.
    """

    async def dependency(request: Request) -> SchemaT | None:
        """Execute dependency.

        Args:
            request: Validated request for this operation.

        Returns:
            SchemaT | None result produced by dependency.
        """
        body = (await request.body()).strip()
        if not body or body == b"null":
            return None
        try:
            return schema_type.model_validate_json(body)
        except ValidationError as exc:
            errors = exc.errors()
            for error in errors:
                error["loc"] = ("body", *error["loc"])
            raise RequestValidationError(errors) from exc

    return dependency
