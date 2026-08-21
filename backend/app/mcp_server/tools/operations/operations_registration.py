"""Register operational readiness and recovery MCP tools."""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.tools.backend_gateway_policy import DEFAULT_SOURCE_AGENT
from app.mcp_server.tools.operations.operations_backend_gateway import (
    alexandria_operational_readiness,
    alexandria_recover,
    alexandria_recovery_run_status,
)
from app.shared.types.extra_types import JSONValue


def register_operations_tools(
    server: MCPServer, api_client: AlexandriaApiClient
) -> None:
    """Register operational readiness and recovery MCP tools.

    Args:
        server: MCPServer server receiving tool registrations.
        api_client: Backend HTTP API client used by tool callbacks.
    """

    @server.tool(name="alexandria_operational_readiness")
    async def _tool_operational_readiness() -> JSONValue:
        """Read operational database, vault, and RAG readiness.

        Returns:
            Backend operational readiness response.
        """
        return await alexandria_operational_readiness(api_client)

    @server.tool(name="alexandria_recover")
    async def _tool_recover(
        dry_run: bool = True,
        trigger: str = "manual",
        actor: str = DEFAULT_SOURCE_AGENT,
        idempotency_key: str | None = None,
        parent_run_id: str | None = None,
    ) -> JSONValue:
        """Diagnose and plan recovery, or apply an explicit idempotent repair.

        Args:
            dry_run: Keep recovery read-only when true; apply planned repairs when false.
            trigger: Recovery plan trigger source.
            actor: Operator or agent requesting the plan.
            idempotency_key: Required when dry_run is false.
            parent_run_id: Optional parent recovery run identifier.

        Returns:
            Backend recovery plan or run response.
        """
        return await alexandria_recover(
            api_client,
            dry_run=dry_run,
            trigger=trigger,
            actor=actor,
            idempotency_key=idempotency_key,
            parent_run_id=parent_run_id,
        )

    @server.tool(name="alexandria_recovery_run_status")
    async def _tool_recovery_run_status(run_id: str) -> JSONValue:
        """Return a persisted operational recovery run by id.

        Args:
            run_id: Recovery run identifier.

        Returns:
            Backend recovery run response.
        """
        return await alexandria_recovery_run_status(
            api_client,
            run_id,
        )
