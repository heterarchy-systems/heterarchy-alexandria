"""Shared strict schemas for low-level HTTP protocol seams."""

from __future__ import annotations

from typing import Annotated

from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ProtocolErrorResponse(StrictSchemaModel):
    """Typed JSON error payload emitted by ASGI protocol boundaries."""

    detail: Annotated[
        str,
        described_field("Human-readable detail for the rejected protocol request."),
    ]
