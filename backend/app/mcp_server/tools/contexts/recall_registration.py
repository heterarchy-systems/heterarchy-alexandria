"""Register the high-level agent-facing recall MCP tool."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.contexts.recall_backend_gateway import alexandria_recall
from app.memory.interface.schemas.context.recall_request_schema import (
    RecallRequestSchema,
)
from app.memory.interface.schemas.context.recall_response_schema import (
    RecallResponseSchema,
)
from app.shared.type_validation.strict_json_arg import json_mode_arg


def register_high_level_recall_tool(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register one high-level recall tool on the MCP server.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_recall")
    async def _tool_recall(
        request: Annotated[
            RecallRequestSchema,
            json_mode_arg(RecallRequestSchema),
        ],
    ) -> RecallResponseSchema:
        """Recall memory through the bounded canonical cascade.

        Args:
            request: Validated high-level recall request payload.

        Returns:
            Typed recall response with provenance and diagnostics.
        """
        return await alexandria_recall(api_client, request)
