"""Strict JSON-mode validation for FastAPI request bodies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.shared.schemas.common_schemas import StrictSchemaModel
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError


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
        try:
            return schema_type.model_validate_json(await request.body())
        except ValidationError as exc:
            errors = exc.errors()
            for error in errors:
                error["loc"] = ("body", *error["loc"])
            raise RequestValidationError(errors) from exc

    return dependency


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
