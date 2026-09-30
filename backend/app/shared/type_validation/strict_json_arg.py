"""Strict JSON-mode validation for framework-decoded tool arguments."""

from __future__ import annotations

from json import dumps
from typing import Any

from pydantic import BaseModel, BeforeValidator, TypeAdapter


def json_mode_arg(
    schema: Any,  # runtime type expression accepted by TypeAdapter (type-contract: allow-any).
) -> BeforeValidator:
    """Build a before-validator that re-validates one tool argument in JSON mode.

    Tool frameworks decode wire JSON into Python values and then validate them
    with Python-mode semantics, so strict schemas reject the enum and datetime
    JSON primitives their own advertised schema promises. This mirrors the
    FastAPI ``json_mode_body`` contract at tool-argument boundaries: the decoded
    value is round-tripped through the same strict JSON-mode validation the
    public schema declares, while already-validated instances pass through.

    Args:
        schema: Pydantic schema class or annotated union advertised for the
            tool argument.

    Returns:
        Before-validator metadata for an ``Annotated`` tool parameter.
    """

    adapter = TypeAdapter(schema)

    def validate(value: object) -> object:
        """Validate one framework-decoded tool argument value.

        Args:
            value: Raw value delivered by the tool framework.

        Returns:
            Strictly validated schema instance.
        """
        if isinstance(value, BaseModel):
            return value
        return adapter.validate_json(dumps(value, allow_nan=False))

    return BeforeValidator(validate)
