"""Register focused Memory Steward readiness and compaction MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.memory_compacts.memory_steward_readiness_tools import (
    alexandria_memory_steward_readiness,
    alexandria_memory_steward_refresh_current_compact,
)
from app.shared.types.extra_types import JSONValue


def register_memory_steward_tools(
    server: MCPServer,
    api_client: AlexandriaApiClient,
) -> None:
    """Register Memory Steward operational tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_memory_steward_readiness")
    async def _tool_memory_steward_readiness(
        project: str | None = None,
        max_compact_age_days: int = 30,
    ) -> JSONValue:
        """Return RAG, Memory Compact, and vault-review readiness."""
        return await alexandria_memory_steward_readiness(
            api_client,
            project=project,
            max_compact_age_days=max_compact_age_days,
        )

    @server.tool(name="alexandria_memory_steward_refresh_current_compact")
    async def _tool_memory_steward_refresh_current_compact(
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ) -> JSONValue:
        """Plan or apply a CURRENT Memory Compact refresh from readiness evidence."""
        return await alexandria_memory_steward_refresh_current_compact(
            api_client,
            project=project,
            max_compact_age_days=max_compact_age_days,
            apply=apply,
            force=force,
            covered_to=covered_to,
        )
