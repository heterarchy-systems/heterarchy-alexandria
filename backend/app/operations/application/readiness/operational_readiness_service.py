"""Read-only operational readiness snapshot service."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from app.operations.application.backup.operational_recovery_history import (
    _active_recovery_run_id,
    _last_successful_recovery_run_id,
)
from app.operations.application.readiness.operational_data_integrity_service import (
    OperationalDataIntegrityService,
)
from app.operations.application.readiness.operational_database_probe import (
    OperationalDatabaseProbe,
)
from app.operations.application.readiness.operational_readiness_cache import (
    OperationalReadinessCache,
)
from app.operations.application.readiness.operational_readiness_contracts import (
    ContextReadinessService,
    ObsidianDataIntegrityService,
    ObsidianReadinessService,
    ReconciliationReadinessService,
)
from app.operations.application.readiness.operational_readiness_policy import (
    _blockers,
    _next_actions,
    _rag_snapshot,
    _reconciliation_snapshot,
    _status,
    _vault_snapshot,
    _warnings,
)
from app.operations.domain.entities.operational_data_integrity import (
    unchecked_data_integrity_snapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextDomainError
from app.shared.infrastructure.database import Database

__all__ = (
    "ContextReadinessService",
    "ObsidianReadinessService",
    "OperationalReadinessService",
    "ReconciliationReadinessService",
)


class OperationalReadinessService:
    """Build operational readiness snapshots without mutating recovery state."""

    def __init__(
        self,
        database: Database,
        context_service: ContextReadinessService,
        obsidian_service: ObsidianReadinessService,
        reconciliation_service: ReconciliationReadinessService | None = None,
        readiness_cache: OperationalReadinessCache | None = None,
        ignore_active_recovery_run_id: str | None = None,
    ) -> None:
        """Create service.

        Args:
            database: Shared database coordinator.
            context_service: Context/RAG service.
            obsidian_service: Obsidian vault service.
            reconciliation_service: Optional reconciliation diagnostics service.
            readiness_cache: Optional fail-open short-lived snapshot cache.
            ignore_active_recovery_run_id: Active run id to ignore for internal
                verification.
        """
        self._database = database
        self._database_probe = OperationalDatabaseProbe(database)
        self._context_service = context_service
        self._obsidian_service = obsidian_service
        self._reconciliation_service = reconciliation_service
        self._readiness_cache = readiness_cache
        self._ignore_active_recovery_run_id = ignore_active_recovery_run_id

    async def snapshot(self) -> OperationalReadinessSnapshot:
        """Return current read-only operational readiness.

        Returns:
            Snapshot composed from database, vault, and RAG diagnostics.
        """
        active_recovery_run_id = _active_recovery_run_id()
        if active_recovery_run_id == self._ignore_active_recovery_run_id:
            active_recovery_run_id = None
        cache = (
            self._readiness_cache
            if self._ignore_active_recovery_run_id is None
            and active_recovery_run_id is None
            else None
        )
        if cache is not None:
            cached = await cache.get()
            if cached is not None:
                return cached
        snapshot = await self._build_snapshot(
            active_recovery_run_id=active_recovery_run_id
        )
        if cache is not None:
            await cache.set(snapshot)
        return snapshot

    async def _build_snapshot(
        self,
        active_recovery_run_id: str | None,
    ) -> OperationalReadinessSnapshot:
        """Probe authoritative dependencies and build one fresh snapshot."""
        started = datetime.now(UTC)
        database = await self._database_probe.snapshot()
        vault_status = await self._obsidian_service.status()
        if isinstance(self._obsidian_service, ObsidianDataIntegrityService):
            data_integrity = await OperationalDataIntegrityService(
                self._obsidian_service
            ).snapshot(vault_status)
        else:
            data_integrity = unchecked_data_integrity_snapshot()
        rag_health = await self._context_service.rag_health_with_index_status()
        vault = _vault_snapshot(vault_status)
        rag = _rag_snapshot(rag_health)
        if self._reconciliation_service is None:
            reconciliation = _reconciliation_snapshot(None, configured=False)
        else:
            try:
                reconciliation_diagnostics = (
                    await self._reconciliation_service.snapshot()
                )
            except (MemoryContextDomainError, OSError, SQLAlchemyError):
                reconciliation = _reconciliation_snapshot(
                    None,
                    configured=True,
                    reachable=False,
                )
            else:
                reconciliation = _reconciliation_snapshot(
                    reconciliation_diagnostics,
                    configured=True,
                )
        last_successful_recovery_run_id = _last_successful_recovery_run_id()
        warnings = _warnings(
            database=database,
            vault=vault,
            rag=rag,
            reconciliation=reconciliation,
        )
        if active_recovery_run_id is not None:
            warnings.append("recovery_in_progress")
        blockers = _blockers(warnings)
        status = _status(
            database=database,
            vault=vault,
            rag=rag,
            warnings=warnings,
            active_recovery_run_id=active_recovery_run_id,
        )
        finished = datetime.now(UTC)
        snapshot = OperationalReadinessSnapshot(
            status=status,
            ready=status is OperationalReadinessStatus.READY,
            checked_at=finished,
            duration_ms=max(int((finished - started).total_seconds() * 1000), 0),
            vault=vault,
            database=database,
            rag=rag,
            reconciliation=reconciliation,
            active_recovery_run_id=active_recovery_run_id,
            last_successful_recovery_run_id=last_successful_recovery_run_id,
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            next_actions=tuple(
                _next_actions(warnings, index_errors=vault_status.index_errors)
            ),
            data_integrity=data_integrity,
        )
        return snapshot
