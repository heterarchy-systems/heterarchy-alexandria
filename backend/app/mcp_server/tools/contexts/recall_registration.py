"""Register the high-level agent-facing recall MCP tool."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.contexts.recall_backend_gateway import alexandria_recall
from app.memory.interface.schemas.context.recall_schema import (
    RecallRequestSchema,
    RecallResponseSchema,
)


def register_high_level_recall_tool(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register one high-level recall tool on the MCP server."""

    @server.tool(name="alexandria_recall")
    async def _tool_recall(request: RecallRequestSchema) -> RecallResponseSchema:
        """Recall memory through the bounded canonical cascade."""
        return await alexandria_recall(api_client, request)
