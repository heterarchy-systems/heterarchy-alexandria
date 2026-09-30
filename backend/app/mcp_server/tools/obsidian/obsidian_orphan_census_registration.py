"""MCP registration for graph orphan census and suggestions."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.obsidian.obsidian_orphan_census_backend_gateway import (
    alexandria_acknowledge_graph_orphan,
    alexandria_get_graph_orphan_status,
    alexandria_list_graph_orphans,
    alexandria_suggest_graph_relations,
)
from app.obsidian.interface.schemas.obsidian.obsidian_orphan_census_schema import (
    ObsidianGraphOrphanAcknowledgeRequest,
    ObsidianGraphOrphanListRequest,
    ObsidianGraphOrphanStatusRequest,
    ObsidianGraphSuggestRelationsRequest,
)
from app.shared.type_validation.strict_json_arg import json_mode_arg
from app.shared.types.extra_types import JSONValue


def register_obsidian_orphan_census_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register bounded orphan census and suggestion tools."""

    @server.tool(name="alexandria_list_graph_orphans")
    async def _tool_list_graph_orphans(
        request: Annotated[
            ObsidianGraphOrphanListRequest,
            json_mode_arg(ObsidianGraphOrphanListRequest),
        ],
    ) -> JSONValue:
        """List graph orphan debt and bounded durable census metadata."""
        return await alexandria_list_graph_orphans(
            api_client,
            request.model_dump(mode="json", exclude_none=True),
        )

    @server.tool(name="alexandria_acknowledge_graph_orphan")
    async def _tool_acknowledge_graph_orphan(
        request: Annotated[
            ObsidianGraphOrphanAcknowledgeRequest,
            json_mode_arg(ObsidianGraphOrphanAcknowledgeRequest),
        ],
    ) -> JSONValue:
        """Record standalone or ignored-with-reason orphan provenance."""
        return await alexandria_acknowledge_graph_orphan(
            api_client,
            request.model_dump(mode="json", exclude_none=True),
        )

    @server.tool(name="alexandria_get_graph_orphan_status")
    async def _tool_get_graph_orphan_status(
        request: Annotated[
            ObsidianGraphOrphanStatusRequest,
            json_mode_arg(ObsidianGraphOrphanStatusRequest),
        ],
    ) -> JSONValue:
        """Read one exact note orphan status from the current projection."""
        return await alexandria_get_graph_orphan_status(
            api_client,
            request.model_dump(mode="json", exclude_none=True),
        )

    @server.tool(name="alexandria_suggest_graph_relations")
    async def _tool_suggest_graph_relations(
        request: Annotated[
            ObsidianGraphSuggestRelationsRequest,
            json_mode_arg(ObsidianGraphSuggestRelationsRequest),
        ],
    ) -> JSONValue:
        """Return evidence-backed relation suggestions without mutation."""
        return await alexandria_suggest_graph_relations(
            api_client,
            request.model_dump(mode="json", exclude_none=True),
        )
