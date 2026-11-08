"""Pydantic schemas for MCP OAuth protected-resource metadata."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.shared.schemas.common_schemas import StrictSchemaModel


class McpProtectedResourceMetadata(StrictSchemaModel):
    """OAuth protected-resource metadata exposed for ChatGPT MCP linking."""

    resource: Annotated[
        str, Field(description="Resource for this MCP protected resource metadata.")
    ]
    authorization_servers: Annotated[
        tuple[str, ...],
        Field(
            description="Authorization servers for this MCP protected resource metadata."
        ),
    ]
    scopes_supported: Annotated[
        tuple[str, ...],
        Field(description="Scopes supported for this MCP protected resource metadata."),
    ]
    bearer_methods_supported: Annotated[
        tuple[str, ...],
        Field(
            description="Bearer methods supported for this MCP protected resource metadata."
        ),
    ] = ("header",)
    resource_documentation: Annotated[
        str | None,
        Field(
            description="Resource documentation for this MCP protected resource metadata."
        ),
    ] = None
