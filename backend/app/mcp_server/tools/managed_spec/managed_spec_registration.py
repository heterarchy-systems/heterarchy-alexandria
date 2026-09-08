"""Register the high-level managed-spec MCP tool."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.managed_spec.managed_spec_backend_gateway import (
    alexandria_execute_managed_spec,
)
from app.obsidian.interface.schemas.managed_spec.managed_spec_schema import (
    ManagedSpecRequestSchema,
    ManagedSpecResponseSchema,
)


def register_managed_spec_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register one discriminated prepare/complete managed-spec tool."""

    @server.tool(name="alexandria_execute_managed_spec")
    async def _tool_execute_managed_spec(
        request: ManagedSpecRequestSchema,
    ) -> ManagedSpecResponseSchema:
        """Prepare or complete a managed specification execution."""
        return await alexandria_execute_managed_spec(api_client, request)
