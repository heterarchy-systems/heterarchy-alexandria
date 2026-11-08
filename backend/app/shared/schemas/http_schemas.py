"""Shared strict schemas for low-level HTTP protocol seams."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.shared.schemas.common_schemas import StrictSchemaModel


class ProtocolErrorResponse(StrictSchemaModel):
    """Typed JSON error payload emitted by ASGI protocol boundaries."""

    detail: Annotated[
        str,
        Field(description="Human-readable detail for the rejected protocol request."),
    ]
