"""MCP registration for high-level Obsidian relation mutation."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.obsidian.obsidian_relation_backend_gateway import (
    alexandria_relate,
)
from app.obsidian.interface.schemas.obsidian.obsidian_relation_schema import (
    ObsidianRelateRequestSchema,
    ObsidianRelateResponse,
)
from app.shared.type_validation.strict_json_arg import json_mode_arg


def register_obsidian_relation_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register the single high-level relation tool.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_relate")
    async def _tool_relate(
        request: Annotated[
            ObsidianRelateRequestSchema,
            json_mode_arg(ObsidianRelateRequestSchema),
        ],
    ) -> ObsidianRelateResponse:
        """Relate two existing notes and verify source, index, and graph state.

        Args:
            request: Validated relation mutation request.

        Returns:
            Relation mutation and verification response.
        """
        return await alexandria_relate(api_client, request)
