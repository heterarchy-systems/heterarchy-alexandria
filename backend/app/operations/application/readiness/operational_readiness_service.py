"""Read-only operational readiness snapshot service."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from typing import Protocol

import anyio
from sqlalchemy.exc import SQLAlchemyError

from app.memory.application.contexts.records.context_service_ports import (
    ContextReadinessPort,
)
from app.memory.application.integration.context_projection_integrity_service import (
    ContextProjectionIntegrityService,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_ports import (
    MemoryReconciliationReadinessPort,
)
from app.memory.domain.entities.context_projection_integrity import (
    unchecked_context_projection_integrity_snapshot,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianDataIntegrityPort,
    ObsidianReadinessPort,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultLocation
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    resolve_vault_path,
)
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
from app.operations.application.readiness.operational_readiness_policy import (
    _blockers,
    _next_actions,
    _rag_snapshot,
    _reconciliation_snapshot,
    _status,
    _vault_snapshot,
    _warnings,
    graph_snapshot_from_status,
)
from app.operations.application.readiness.operational_retrieval_canary_service import (
    OperationalRetrievalCanaryService,
)
from app.operations.application.readiness.operational_runtime_provenance_service import (
    OperationalRuntimeProvenanceService,
)
from app.operations.domain.entities.operational_data_integrity import (
    unchecked_data_integrity_snapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
    OperationalVaultSnapshot,
)
from app.operations.domain.entities.operational_retrieval_canary import (
    unchecked_retrieval_canary_snapshot,
)
from app.operations.domain.entities.operational_runtime_provenance import (
    unchecked_runtime_provenance_snapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextDomainError
from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError
from app.shared.infrastructure.database import Database

__all__ = (
    "ContextReadinessPort",
    "MemoryReconciliationReadinessPort",
    "ObsidianReadinessPort",
    "OperationalReadinessService",
)


class GraphProjectionReadinessPort(Protocol):
    """Read-only graph projection status boundary."""

    async def status(self) -> ObsidianGraphProjectionStatusReport:
        """Return current graph projection status."""


@dataclass(frozen=True, slots=True)
class _SourceProbe:
    """Bounded source-directory availability evidence."""

    exists: bool
    root_exists: bool
    readable: bool
    warning: str | None = None


def _vault_snapshot_from_probe(
    location: ObsidianVaultLocation,
    probe: _SourceProbe,
) -> OperationalVaultSnapshot:
    """Build source evidence with unknown metadata counts."""
    return OperationalVaultSnapshot(
        exists=probe.exists,
        readable=probe.readable,
        vault_path=location.vault_path,
        alexandria_root=location.alexandria_root,
        alexandria_root_exists=probe.root_exists,
        indexed_notes=None,
        stale_notes=None,
        error_notes=None,
    )


async def _probe_source_location(location: ObsidianVaultLocation) -> _SourceProbe:
    """Probe one source directory through the bounded framework worker lane."""
    return await anyio.to_thread.run_sync(
        partial(_probe_source_location_sync, location),
        limiter=anyio.to_thread.current_default_thread_limiter(),
    )


def _probe_source_location_sync(location: ObsidianVaultLocation) -> _SourceProbe:
    """Read at most one directory entry to prove source availability."""
    try:
        vault = resolve_vault_path(location.vault_path)
        root = resolve_note_path(vault, location.alexandria_root)
    except (ObsidianDomainError, OSError, ValueError):
        return _SourceProbe(False, False, False, "source_path_invalid")
    if not vault.exists():
        return _SourceProbe(False, False, False, "source_unavailable")
    if not root.exists():
        return _SourceProbe(True, False, False, "source_root_unavailable")
    try:
        with os.scandir(root) as entries:
            next(entries, None)
    except OSError:
        return _SourceProbe(True, True, False, "source_unreadable")
    return _SourceProbe(True, True, True)


def _unknown_rag_health() -> RagDependencyHealth:
    """Return typed RAG diagnostics without asserting healthy or empty state."""
    return RagDependencyHealth(
        fts=RagHealthState.DEGRADED,
        vector=RagHealthState.DEGRADED,
        embedding=RagHealthState.DEGRADED,
        default_strategy=RagStrategy.FTS_ONLY,
        model_name="unknown",
        dimensions=0,
        fingerprint=None,
        warnings=("rag_health_unavailable",),
    )


class OperationalReadinessService:
    """Build operational readiness snapshots without mutating recovery state."""

    def __init__(
        self,
        database: Database,
        context_service: ContextReadinessPort,
        obsidian_service: ObsidianReadinessPort,
        reconciliation_service: MemoryReconciliationReadinessPort | None = None,
        readiness_cache: OperationalReadinessCache | None = None,
        ignore_active_recovery_run_id: str | None = None,
        runtime_provenance_service: OperationalRuntimeProvenanceService | None = None,
        retrieval_canary_service: OperationalRetrievalCanaryService | None = None,
        projection_integrity_service: ContextProjectionIntegrityService | None = None,
        *,
        graph_projection_service: GraphProjectionReadinessPort,
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
            runtime_provenance_service: Optional runtime build identity probe.
            retrieval_canary_service: Optional bounded real-search readiness probe.
            projection_integrity_service: Optional persisted full projection integrity reader.
            graph_projection_service: Optional graph projection status reader.
        """
        self._database = database
        self._database_probe = OperationalDatabaseProbe(database)
        self._context_service = context_service
        self._obsidian_service = obsidian_service
        self._reconciliation_service = reconciliation_service
        self._readiness_cache = readiness_cache
        self._ignore_active_recovery_run_id = ignore_active_recovery_run_id
        self._runtime_provenance_service = runtime_provenance_service
        self._retrieval_canary_service = retrieval_canary_service
        self._projection_integrity_service = projection_integrity_service
        self._graph_projection_service = graph_projection_service

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
        """Probe authoritative dependencies and build one fresh snapshot.

        Args:
            active_recovery_run_id: Identifier for active recovery run.

        Returns:
            Constructed snapshot.
        """
        started = datetime.now(UTC)
        database = await self._database_probe.snapshot()
        metadata_warning: str | None = None
        if database.reachable:
            try:
                vault_status = await self._obsidian_service.status()
            except (SQLAlchemyError, ObsidianDomainError, OSError, ValueError):
                vault_status = None
                metadata_warning = "metadata_index_unavailable"
        else:
            vault_status = None
            metadata_warning = "metadata_index_skipped_database_unavailable"
        if vault_status is None:
            try:
                location = self._obsidian_service.vault_location()
            except (ObsidianDomainError, OSError, ValueError):
                source_probe = _SourceProbe(
                    exists=False,
                    root_exists=False,
                    readable=False,
                    warning="source_probe_unavailable",
                )
                source_location = ObsidianVaultLocation(
                    vault_path="",
                    alexandria_root=".",
                )
            else:
                source_location = location
                source_probe = await _probe_source_location(location)
        else:
            source_location = ObsidianVaultLocation(
                vault_path=vault_status.vault_path,
                alexandria_root=vault_status.alexandria_root,
            )
            source_probe = await _probe_source_location(source_location)

        if vault_status is not None and isinstance(
            self._obsidian_service, ObsidianDataIntegrityPort
        ):
            data_integrity = await OperationalDataIntegrityService(
                self._obsidian_service
            ).snapshot(vault_status)
        else:
            data_integrity = unchecked_data_integrity_snapshot()
        if vault_status is None:
            vault = _vault_snapshot_from_probe(source_location, source_probe)
            index_errors = ()
        else:
            vault = replace(
                _vault_snapshot(vault_status),
                exists=source_probe.exists,
                readable=source_probe.readable,
                alexandria_root_exists=source_probe.root_exists,
            )
            index_errors = vault_status.index_errors
        rag_warning: str | None = None
        try:
            if not database.reachable:
                raise SQLAlchemyError("database unavailable")
            rag_health = await self._context_service.rag_health_with_index_status()
        except (SQLAlchemyError, MemoryContextDomainError, OSError, ValueError):
            rag_health = _unknown_rag_health()
            rag_warning = (
                "rag_health_skipped_database_unavailable"
                if not database.reachable
                else "rag_health_unavailable"
            )
        rag = _rag_snapshot(rag_health)
        runtime_warning: str | None = None
        try:
            runtime = (
                self._runtime_provenance_service.snapshot()
                if self._runtime_provenance_service is not None
                else unchecked_runtime_provenance_snapshot()
            )
        except (OSError, ValueError, ObsidianDomainError):
            runtime = unchecked_runtime_provenance_snapshot()
            runtime_warning = "runtime_provenance_unavailable"
        retrieval_warning: str | None = None
        try:
            if not database.reachable:
                raise SQLAlchemyError("database unavailable")
            retrieval_canary = (
                await self._retrieval_canary_service.snapshot()
                if self._retrieval_canary_service is not None
                else unchecked_retrieval_canary_snapshot()
            )
        except (SQLAlchemyError, MemoryContextDomainError, OSError, ValueError):
            retrieval_canary = unchecked_retrieval_canary_snapshot()
            retrieval_warning = (
                "retrieval_canary_skipped_database_unavailable"
                if not database.reachable
                else "retrieval_canary_unavailable"
            )
        projection_warning: str | None = None
        try:
            if not database.reachable:
                raise SQLAlchemyError("database unavailable")
            projection_integrity = (
                await self._projection_integrity_service.snapshot()
                if self._projection_integrity_service is not None
                else unchecked_context_projection_integrity_snapshot()
            )
        except (SQLAlchemyError, MemoryContextDomainError, OSError, ValueError):
            projection_integrity = unchecked_context_projection_integrity_snapshot()
            projection_warning = (
                "projection_integrity_skipped_database_unavailable"
                if not database.reachable
                else "projection_integrity_unavailable"
            )
        graph_warning: str | None = None
        try:
            if not database.reachable:
                raise SQLAlchemyError("database unavailable")
            graph = graph_snapshot_from_status(
                await self._graph_projection_service.status()
            )
        except (SQLAlchemyError, OSError, ValueError, ObsidianDomainError):
            graph = graph_snapshot_from_status(None)
            graph_warning = (
                "graph_projection_skipped_database_unavailable"
                if not database.reachable
                else "graph_projection_unavailable"
            )
        if self._reconciliation_service is None:
            reconciliation = _reconciliation_snapshot(None, configured=False)
        elif not database.reachable:
            reconciliation = _reconciliation_snapshot(
                None,
                configured=True,
                reachable=False,
            )
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
            runtime=runtime,
            retrieval_canary=retrieval_canary,
            projection_integrity=projection_integrity,
            reconciliation=reconciliation,
        )
        for warning in (
            metadata_warning,
            source_probe.warning,
            rag_warning,
            runtime_warning,
            retrieval_warning,
            projection_warning,
            graph_warning,
        ):
            if warning is not None:
                warnings.append(warning)
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
            next_actions=tuple(_next_actions(warnings, index_errors=index_errors)),
            data_integrity=data_integrity,
            runtime=runtime,
            retrieval_canary=retrieval_canary,
            projection_integrity=projection_integrity,
            graph=graph,
        )
        return snapshot
