"""Register Context lifecycle and RAG status MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.contexts.context_backend_gateway import (
    alexandria_archive_context,
    alexandria_delete_context,
    alexandria_rag_status,
    alexandria_supersede_context,
)
from app.shared.types.extra_types import JSONValue


def register_context_lifecycle_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register Context lifecycle and RAG status MCP tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_archive_context")
    async def _tool_archive_context(context_id: str) -> JSONValue:
        """Archive a Context Vault entry without hard delete.

        Args:
            context_id: Context identifier.

        Returns:
            Archived context response.
        """
        return await alexandria_archive_context(api_client, context_id)

    @server.tool(name="alexandria_supersede_context")
    async def _tool_supersede_context(
        context_id: str,
        replacement_context_id: str,
    ) -> JSONValue:
        """Link a canonical Context to an existing replacement.

        Args:
            context_id: Context identifier to supersede.
            replacement_context_id: Replacement Context identifier.

        Returns:
            Superseded and replacement Context response.
        """
        return await alexandria_supersede_context(
            api_client,
            context_id,
            replacement_context_id,
        )

    @server.tool(name="alexandria_delete_context")
    async def _tool_delete_context(context_id: str) -> JSONValue:
        """Hard delete one Context Vault entry.

        Args:
            context_id: Context identifier.

        Returns:
            Backend delete response, typically null for HTTP 204.
        """
        return await alexandria_delete_context(api_client, context_id)

    @server.tool(name="alexandria_rag_status")
    async def _tool_rag_status() -> JSONValue:
        """Read Context RAG health status.

        Returns:
            Backend RAG health response.
        """
        return await alexandria_rag_status(api_client)
