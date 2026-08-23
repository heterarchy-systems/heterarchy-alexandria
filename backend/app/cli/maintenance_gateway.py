"""Gateway wrapper for Memory Steward and Vault CLI backend calls."""

from __future__ import annotations

from app.cli.type_validate.command_options import (
    MemoryCompactRefreshOptions,
    MemoryStewardReadinessOptions,
    VaultReviewApplyOptions,
    VaultReviewOptions,
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

    async def alexandria_vault_review_queue(
        self,
        client: AlexandriaApiClient,
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
    ) -> JSONValue:
        """Call the vault review queue backend operation.

        Args:
            client: Backend HTTP client.
            project: Optional project filter.
            scope_path: Optional vault-relative scope.
            limit: Maximum candidates.

        Returns:
            JSON-compatible review queue payload.
        """
        # local import justified: CLI help must not import the broad MCP gateway.
        from app.mcp_server.tools.obsidian.vault_maintenance_backend_gateway import (
            alexandria_vault_review_queue,
        )

        return await alexandria_vault_review_queue(
            client,
            project=project,
            scope_path=scope_path,
            limit=limit,
        )

    async def alexandria_vault_review_move_plan(
        self,
        client: AlexandriaApiClient,
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
    ) -> JSONValue:
        """Call the vault review move-plan backend operation.

        Args:
            client: Backend HTTP client.
            project: Optional project filter.
            scope_path: Optional vault-relative scope.
            limit: Maximum candidates.

        Returns:
            JSON-compatible move-plan payload.
        """
        # local import justified: CLI help must not import the broad MCP gateway.
        from app.mcp_server.tools.obsidian.vault_maintenance_backend_gateway import (
            alexandria_vault_review_move_plan,
        )

        return await alexandria_vault_review_move_plan(
            client,
            project=project,
            scope_path=scope_path,
            limit=limit,
        )

    async def alexandria_vault_review_apply_moves(
        self,
        client: AlexandriaApiClient,
        project: str | None = None,
        scope_path: str | None = None,
        limit: int = 20,
        report_path: str | None = None,
        reindex: bool = True,
        verification_query: str | None = None,
        confirm_apply: bool = False,
    ) -> JSONValue:
        """Call the vault review apply backend operation.

        Args:
            client: Backend HTTP client.
            project: Optional project filter.
            scope_path: Optional vault-relative scope.
            limit: Maximum candidates.
            report_path: Optional report path.
            reindex: Whether to rebuild the index after moving.
            verification_query: Optional post-move verification query.
            confirm_apply: Whether the caller confirmed mutation.

        Returns:
            JSON-compatible move application payload.
        """
        # local import justified: CLI help must not import the broad MCP gateway.
        from app.mcp_server.tools.obsidian.vault_maintenance_backend_gateway import (
            alexandria_vault_review_apply_moves,
        )

        return await alexandria_vault_review_apply_moves(
            client,
            project=project,
            scope_path=scope_path,
            limit=limit,
            report_path=report_path,
            reindex=reindex,
            verification_query=verification_query,
            confirm_apply=confirm_apply,
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

    async def review_queue(self, options: VaultReviewOptions) -> JSONValue:
        """Return notes waiting for vault review.

        Args:
            options: Review queue command options.

        Returns:
            JSON-compatible review queue payload.
        """
        return await backend_tool_gateway.alexandria_vault_review_queue(
            self._client,
            project=options.project,
            scope_path=options.scope_path,
            limit=options.limit,
        )

    async def review_move_plan(self, options: VaultReviewOptions) -> JSONValue:
        """Return a dry-run move plan for safe review queue candidates.

        Args:
            options: Review move-plan command options.

        Returns:
            JSON-compatible move-plan payload.
        """
        return await backend_tool_gateway.alexandria_vault_review_move_plan(
            self._client,
            project=options.project,
            scope_path=options.scope_path,
            limit=options.limit,
        )

    async def review_apply_moves(self, options: VaultReviewApplyOptions) -> JSONValue:
        """Apply confirmed safe review queue moves.

        Args:
            options: Review apply command options.

        Returns:
            JSON-compatible apply result payload.
        """
        return await backend_tool_gateway.alexandria_vault_review_apply_moves(
            self._client,
            project=options.review.project,
            scope_path=options.review.scope_path,
            limit=options.review.limit,
            report_path=options.report_path,
            reindex=options.reindex,
            verification_query=options.verification_query,
            confirm_apply=options.confirm_apply,
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
