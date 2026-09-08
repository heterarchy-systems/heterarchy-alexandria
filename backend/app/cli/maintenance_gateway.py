"""Gateway wrapper for Memory Steward CLI backend calls."""

from __future__ import annotations

from app.cli.type_validate.command_options import (
    MemoryCompactRefreshOptions,
    MemoryStewardReadinessOptions,
)
from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.shared.types.extra_types import JSONValue


class _BackendMaintenanceGatewayAdapter:
    """Expose only maintenance CLI operations while preserving deferred imports."""

    async def alexandria_memory_steward_readiness(
        self,
        client: AlexandriaApiClient,
        project: str | None = None,
        max_compact_age_days: int = 30,
    ) -> JSONValue:
        """Call the Memory Steward readiness backend operation.

        Args:
            client: Backend HTTP client.
            project: Optional project filter.
            max_compact_age_days: Maximum acceptable compact age.

        Returns:
            JSON-compatible readiness payload.
        """
        # local import justified: CLI help must not import the broad MCP gateway.
        from app.mcp_server.tools.memory_compacts.memory_steward_readiness_tools import (
            alexandria_memory_steward_readiness,
        )

        return await alexandria_memory_steward_readiness(
            client,
            project=project,
            max_compact_age_days=max_compact_age_days,
        )

    async def alexandria_memory_steward_refresh_current_compact(
        self,
        client: AlexandriaApiClient,
        project: str | None = None,
        max_compact_age_days: int = 30,
        apply: bool = False,
        force: bool = False,
        covered_to: str | None = None,
    ) -> JSONValue:
        """Call the Memory Steward compact refresh backend operation.

        Args:
            client: Backend HTTP client.
            project: Optional project filter.
            max_compact_age_days: Maximum acceptable compact age.
            apply: Whether to create a replacement compact.
            force: Whether to refresh despite fresh readiness.
            covered_to: Optional deterministic coverage end.

        Returns:
            JSON-compatible compact refresh payload.
        """
        # local import justified: CLI help must not import the broad MCP gateway.
        from app.mcp_server.tools.memory_compacts.memory_steward_readiness_tools import (
            alexandria_memory_steward_refresh_current_compact,
        )

        return await alexandria_memory_steward_refresh_current_compact(
            client,
            project=project,
            max_compact_age_days=max_compact_age_days,
            apply=apply,
            force=force,
            covered_to=covered_to,
        )


backend_tool_gateway = _BackendMaintenanceGatewayAdapter()


class MaintenanceGateway:
    """Call maintenance backend functions with shared client state."""

    def __init__(self, client: AlexandriaApiClient) -> None:
        """Initialize MaintenanceGateway state and dependencies.

        Args:
            client: Client used by this operation.
        """
        self._client = client

    async def readiness(self, options: MemoryStewardReadinessOptions) -> JSONValue:
        """Return Memory Steward readiness for the configured project scope.

        Args:
            options: Readiness command options.

        Returns:
            JSON-compatible readiness payload.
        """
        return await backend_tool_gateway.alexandria_memory_steward_readiness(
            self._client,
            project=options.project,
            max_compact_age_days=options.max_compact_age_days,
        )

    async def refresh_current_compact(
        self, options: MemoryCompactRefreshOptions
    ) -> JSONValue:
        """Plan or apply a CURRENT Memory Compact refresh.

        Args:
            options: Compact refresh command options.

        Returns:
            JSON-compatible compact refresh payload.
        """
        return await backend_tool_gateway.alexandria_memory_steward_refresh_current_compact(
            self._client,
            project=options.project,
            max_compact_age_days=options.max_compact_age_days,
            apply=options.apply,
            force=options.force,
            covered_to=options.covered_to,
        )
