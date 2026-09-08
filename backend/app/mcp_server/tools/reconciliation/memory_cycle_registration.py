"""MCP registration for the high-level memory-cycle operation."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.reconciliation.memory_cycle_backend_gateway import (
    alexandria_memory_cycle,
)
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_schema import (
    MemoryCycleRequestSchema,
    MemoryCycleResponseSchema,
)


def register_memory_cycle_tool(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register one typed high-level memory-cycle tool."""

    @server.tool(name="alexandria_memory_cycle")
    async def _tool_memory_cycle(
        request: MemoryCycleRequestSchema,
    ) -> MemoryCycleResponseSchema:
        """Preview or apply one exact aggregate memory cycle."""
        return await alexandria_memory_cycle(api_client, request)
