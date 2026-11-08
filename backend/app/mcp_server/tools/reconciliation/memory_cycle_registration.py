"""MCP registration for the high-level memory-cycle operation."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.reconciliation.memory_cycle_backend_gateway import (
    alexandria_memory_cycle,
)
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_request_schema import (
    MemoryCycleRequestSchema,
)
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_response_schema import (
    MemoryCycleResponseSchema,
)
from app.shared.type_validation.strict_json_arg import json_mode_arg


def register_memory_cycle_tool(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register one typed high-level memory-cycle tool.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_memory_cycle")
    async def _tool_memory_cycle(
        request: Annotated[
            MemoryCycleRequestSchema,
            json_mode_arg(MemoryCycleRequestSchema),
        ],
    ) -> MemoryCycleResponseSchema:
        """Preview or apply one exact aggregate memory cycle."""
        return await alexandria_memory_cycle(api_client, request)
