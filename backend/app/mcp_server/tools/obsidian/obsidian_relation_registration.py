"""MCP registration for high-level Obsidian relation mutation."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.obsidian.obsidian_relation_backend_gateway import (
    alexandria_relate,
)
from app.obsidian.interface.schemas.obsidian.obsidian_relation_schema import (
    ObsidianRelateRequestSchema,
    ObsidianRelateResponse,
)


def register_obsidian_relation_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register the single high-level relation tool."""

    @server.tool(name="alexandria_relate")
    async def _tool_relate(
        request: ObsidianRelateRequestSchema,
    ) -> ObsidianRelateResponse:
        """Relate two existing notes and verify source, index, and graph state."""
        return await alexandria_relate(api_client, request)
