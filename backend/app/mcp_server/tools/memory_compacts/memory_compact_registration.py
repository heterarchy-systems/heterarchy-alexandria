"""Register read-only Memory Compact MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.memory_compacts.memory_compact_tools import (
    alexandria_get_current_memory_compact,
    alexandria_get_memory_compact,
    alexandria_list_memory_compact_artifacts,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.shared.types.extra_types import JSONValue


def register_memory_compact_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register read-only compact discovery tools for requesting agents.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by callbacks.
    """

    @server.tool(name="alexandria_list_memory_compact_artifacts")
    async def _tool_list_memory_compact_artifacts(
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JSONValue:
        """List durable Memory Compact artifacts."""
        return await alexandria_list_memory_compact_artifacts(
            api_client,
            project=project,
            status=status,
            limit=limit,
            offset=offset,
        )

    @server.tool(name="alexandria_get_current_memory_compact")
    async def _tool_get_current_memory_compact(
        project: str | None = None,
    ) -> JSONValue:
        """Read the current Memory Compact for a project."""
        return await alexandria_get_current_memory_compact(api_client, project)

    @server.tool(name="alexandria_get_memory_compact")
    async def _tool_get_memory_compact(compact_id: str) -> JSONValue:
        """Read one selected Memory Compact by id."""
        return await alexandria_get_memory_compact(api_client, compact_id)
