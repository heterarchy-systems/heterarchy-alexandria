"""Mutation operations executed by an operational recovery run."""

from __future__ import annotations

from app.operations.application.recovery.execution.recovery_run_contracts import (
    ContextRecoveryService,
    ContextRecoveryServiceFactory,
    ObsidianRecoveryService,
    ObsidianRecoveryServiceFactory,
    resolve_recovery_service,
)
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject


class RecoveryRunMutationOperations:
    """Execute destructive and rebuild steps through explicit service boundaries."""

    def __init__(
        self,
        database: Database,
        context_service: ContextRecoveryService,
        obsidian_service: ObsidianRecoveryService,
        context_service_factory: ContextRecoveryServiceFactory | None = None,
        obsidian_service_factory: ObsidianRecoveryServiceFactory | None = None,
    ) -> None:
        """Initialize recovery mutation dependencies.

        Args:
            database: Shared database coordinator.
            context_service: Context embedding recovery boundary.
            obsidian_service: Obsidian index recovery boundary.
        """
        self._database = database
        self._context_service_factory = context_service_factory or (
            lambda: context_service
        )
        self._obsidian_service_factory = obsidian_service_factory or (
            lambda: obsidian_service
        )

    async def reindex_vault(self) -> JSONObject:
        async with self._database.request_session() as session:
            try:
                service = await resolve_recovery_service(self._obsidian_service_factory)
                result = await service.reindex()
            except Exception:
                await session.rollback()
                raise
            await session.commit()
        return {
            "files_seen": result.files_seen,
            "files_indexed": result.files_indexed,
            "files_skipped": result.files_skipped,
            "stale_marked": result.stale_marked,
            "errors": list(result.errors),
        }

    async def reindex_embeddings(self) -> JSONObject:
        async with self._database.request_session() as session:
            try:
                service = await resolve_recovery_service(self._context_service_factory)
                result = await service.reindex_embeddings(limit=250, force=False)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
        return {
            "scanned": result.scanned,
            "updated": result.updated,
            "skipped": result.skipped,
            "warnings": list(result.warnings),
        }
