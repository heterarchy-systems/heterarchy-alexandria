"""Pydantic schemas for MCP OAuth protected-resource metadata."""

from __future__ import annotations

from typing import Annotated

from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class McpProtectedResourceMetadata(StrictSchemaModel):
    """OAuth protected-resource metadata exposed for ChatGPT MCP linking."""

    resource: Annotated[
        str, described_field("Resource for this MCP protected resource metadata.")
    ]
    authorization_servers: Annotated[
        tuple[str, ...],
        described_field(
            "Authorization servers for this MCP protected resource metadata."
        ),
    ]
    scopes_supported: Annotated[
        tuple[str, ...],
        described_field("Scopes supported for this MCP protected resource metadata."),
    ]
    bearer_methods_supported: Annotated[
        tuple[str, ...],
        described_field(
            "Bearer methods supported for this MCP protected resource metadata."
        ),
    ] = ("header",)
    resource_documentation: Annotated[
        str | None,
        described_field(
            "Resource documentation for this MCP protected resource metadata."
        ),
    ] = None
