"""Read-only operational readiness snapshot service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

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
    ContextProjectionIntegritySnapshot,
    unchecked_context_projection_integrity_snapshot,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianDataIntegrityPort,
    ObsidianReadinessPort,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianIndexError
from app.operations.application.backup.operational_recovery_history import (
    active_recovery_run_id,
    last_successful_recovery_run_id,
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
from app.operations.application.readiness.operational_retrieval_canary_service import (
    OperationalRetrievalCanaryService,
)
from app.operations.application.readiness.operational_runtime_provenance_service import (
    OperationalRuntimeProvenanceService,
)
from app.operations.application.readiness.operational_source_probe import (
    probe_vault_source,
    unknown_rag_health,
)
from app.operations.application.readiness.policy.operational_compile_receipt_policy import (
    compile_receipt_snapshot,
)
from app.operations.application.readiness.policy.operational_readiness_policy import (
    next_actions,
    readiness_blockers,
    readiness_status,
    readiness_warnings,
)
from app.operations.application.readiness.policy.operational_subsystem_snapshots import (
    graph_snapshot_from_status,
    rag_snapshot,
    reconciliation_snapshot,
)
from app.operations.domain.entities.operational_data_integrity import (
    OperationalDataIntegritySnapshot,
    unchecked_data_integrity_snapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalCompileReceiptSnapshot,
    OperationalDatabaseSnapshot,
    OperationalGraphSnapshot,
    OperationalRagSnapshot,
    OperationalReadinessSnapshot,
    OperationalReconciliationSnapshot,
    OperationalVaultSnapshot,
)
from app.operations.domain.entities.operational_retrieval_canary import (
    OperationalRetrievalCanarySnapshot,
    unchecked_retrieval_canary_snapshot,
)
from app.operations.domain.entities.operational_runtime_provenance import (
    OperationalRuntimeProvenanceSnapshot,
    unchecked_runtime_provenance_snapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    CompileReceiptStatus,
    OperationalReadinessStatus,
    OperationalReadinessWarningCode as _WarnCode,
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

type _VaultProbeResult = tuple[
    OperationalVaultSnapshot,
    OperationalDataIntegritySnapshot,
    tuple[ObsidianIndexError, ...],
    tuple[str | None, str | None],
]
type _DatabaseDependentsProbeResult = tuple[
    OperationalRagSnapshot,
    OperationalRuntimeProvenanceSnapshot,
    OperationalRetrievalCanarySnapshot,
    ContextProjectionIntegritySnapshot,
    OperationalGraphSnapshot,
    tuple[str | None, ...],
]


class GraphProjectionReadinessPort(Protocol):
    """Read-only graph projection status boundary."""

    async def status(self) -> ObsidianGraphProjectionStatusReport:
        """Return current graph projection status.

        Returns:
            Current graph projection status report.
        """


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
        compile_receipt_required: bool = False,
        expected_compile_policy_version: str | None = None,
        expected_compile_plan_fingerprint: str | None = None,
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
            compile_receipt_required: Whether this path requires compiler evidence.
            expected_compile_policy_version: Current compiler policy fingerprint when known.
            expected_compile_plan_fingerprint: Exact compile plan expected by the
                successful compile path when known.
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
        self._compile_receipt_required = compile_receipt_required
        self._expected_compile_policy_version = expected_compile_policy_version
        self._expected_compile_plan_fingerprint = expected_compile_plan_fingerprint

    async def snapshot(self) -> OperationalReadinessSnapshot:
        """Return current read-only operational readiness.

        Returns:
            Snapshot composed from database, vault, and RAG diagnostics.
        """
        active_run_id = active_recovery_run_id()
        if active_run_id == self._ignore_active_recovery_run_id:
            active_run_id = None
        cache = (
            self._readiness_cache
            if self._ignore_active_recovery_run_id is None
            and active_run_id is None
            and not self._compile_receipt_required
            and self._expected_compile_policy_version is None
            and self._expected_compile_plan_fingerprint is None
            else None
        )
        if cache is not None:
            cached = await cache.get()
            if cached is not None:
                return cached
        snapshot = await self._build_snapshot(active_recovery_run_id=active_run_id)
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
        (
            vault,
            data_integrity,
            index_errors,
            vault_warnings,
        ) = await self._probe_vault_and_integrity(database)
        (
            rag,
            runtime,
            retrieval_canary,
            projection_integrity,
            graph,
            dep_warnings,
        ) = await self._probe_database_dependents(database)
        reconciliation, compile_receipt = await self._probe_reconciliation_and_receipt(
            database
        )
        warnings = readiness_warnings(
            database=database,
            vault=vault,
            rag=rag,
            runtime=runtime,
            retrieval_canary=retrieval_canary,
            projection_integrity=projection_integrity,
            reconciliation=reconciliation,
        )
        warnings.extend(w for w in (*vault_warnings, *dep_warnings) if w is not None)
        if active_recovery_run_id is not None:
            warnings.append(_WarnCode.RECOVERY_IN_PROGRESS.value)
        warnings.extend(compile_receipt.warnings)
        warnings.extend(compile_receipt.blockers)
        blockers = readiness_blockers(warnings)
        status = readiness_status(
            database=database,
            vault=vault,
            rag=rag,
            warnings=warnings,
            active_recovery_run_id=active_recovery_run_id,
        )
        finished = datetime.now(UTC)
        return OperationalReadinessSnapshot(
            status=status,
            ready=status is OperationalReadinessStatus.READY,
            checked_at=finished,
            duration_ms=max(int((finished - started).total_seconds() * 1000), 0),
            vault=vault,
            database=database,
            rag=rag,
            reconciliation=reconciliation,
            active_recovery_run_id=active_recovery_run_id,
            last_successful_recovery_run_id=last_successful_recovery_run_id(),
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            next_actions=tuple(next_actions(warnings, index_errors=index_errors)),
            data_integrity=data_integrity,
            runtime=runtime,
            retrieval_canary=retrieval_canary,
            projection_integrity=projection_integrity,
            graph=graph,
            compile_receipt=compile_receipt,
        )

    async def _probe_vault_and_integrity(
        self,
        database: OperationalDatabaseSnapshot,
    ) -> _VaultProbeResult:
        """Probe vault metadata index, filesystem availability, and data integrity.

        Args:
            database: Current database reachability snapshot.

        Returns:
            Tuple of vault snapshot, data integrity snapshot, index errors, and
            metadata/source probe warnings.
        """
        metadata_warning: str | None = None
        vault_status = None
        if database.reachable:
            try:
                vault_status = await self._obsidian_service.status()
            except SQLAlchemyError, ObsidianDomainError, OSError, ValueError:
                metadata_warning = _WarnCode.METADATA_INDEX_UNAVAILABLE.value
        else:
            metadata_warning = (
                _WarnCode.METADATA_INDEX_SKIPPED_DATABASE_UNAVAILABLE.value
            )
        vault, index_errors, source_warning = await probe_vault_source(
            self._obsidian_service, vault_status
        )
        data_integrity = (
            await OperationalDataIntegrityService(self._obsidian_service).snapshot(
                vault_status
            )
            if vault_status is not None
            and isinstance(self._obsidian_service, ObsidianDataIntegrityPort)
            else unchecked_data_integrity_snapshot()
        )
        return (
            vault,
            data_integrity,
            index_errors,
            (metadata_warning, source_warning),
        )

    async def _probe_database_dependents(
        self,
        database: OperationalDatabaseSnapshot,
    ) -> _DatabaseDependentsProbeResult:
        """Probe RAG health, runtime provenance, retrieval canary, projection integrity, and graph status.

        Args:
            database: Current database reachability snapshot.

        Returns:
            Tuple of RAG, runtime provenance, retrieval canary, projection
            integrity, and graph snapshots plus collected warning codes.
        """
        warnings: list[str | None] = []
        try:
            runtime = (
                self._runtime_provenance_service.snapshot()
                if self._runtime_provenance_service is not None
                else unchecked_runtime_provenance_snapshot()
            )
        except OSError, ValueError, ObsidianDomainError:
            runtime = unchecked_runtime_provenance_snapshot()
            warnings.append(_WarnCode.RUNTIME_PROVENANCE_UNAVAILABLE.value)
        if not database.reachable:
            skipped = (
                _WarnCode.RAG_HEALTH_SKIPPED_DATABASE_UNAVAILABLE.value,
                *warnings,
                _WarnCode.RETRIEVAL_CANARY_SKIPPED_DATABASE_UNAVAILABLE.value,
                _WarnCode.PROJECTION_INTEGRITY_SKIPPED_DATABASE_UNAVAILABLE.value,
                _WarnCode.GRAPH_PROJECTION_SKIPPED_DATABASE_UNAVAILABLE.value,
            )
            return (
                rag_snapshot(unknown_rag_health()),
                runtime,
                unchecked_retrieval_canary_snapshot(),
                unchecked_context_projection_integrity_snapshot(),
                graph_snapshot_from_status(None),
                skipped,
            )
        try:
            rag_health = await self._context_service.rag_health_with_index_status()
        except SQLAlchemyError, MemoryContextDomainError, OSError, ValueError:
            rag_health = unknown_rag_health()
            warnings.insert(0, _WarnCode.RAG_HEALTH_UNAVAILABLE.value)
        rag = rag_snapshot(rag_health)
        try:
            retrieval_canary = (
                await self._retrieval_canary_service.snapshot()
                if self._retrieval_canary_service is not None
                else unchecked_retrieval_canary_snapshot()
            )
        except SQLAlchemyError, MemoryContextDomainError, OSError, ValueError:
            retrieval_canary = unchecked_retrieval_canary_snapshot()
            warnings.append(_WarnCode.RETRIEVAL_CANARY_UNAVAILABLE.value)
        try:
            projection_integrity = (
                await self._projection_integrity_service.snapshot()
                if self._projection_integrity_service is not None
                else unchecked_context_projection_integrity_snapshot()
            )
        except SQLAlchemyError, MemoryContextDomainError, OSError, ValueError:
            projection_integrity = unchecked_context_projection_integrity_snapshot()
            warnings.append(_WarnCode.PROJECTION_INTEGRITY_UNAVAILABLE.value)
        try:
            graph = graph_snapshot_from_status(
                await self._graph_projection_service.status()
            )
        except SQLAlchemyError, OSError, ValueError, ObsidianDomainError:
            graph = graph_snapshot_from_status(None)
            warnings.append(_WarnCode.GRAPH_PROJECTION_UNAVAILABLE.value)
        return (
            rag,
            runtime,
            retrieval_canary,
            projection_integrity,
            graph,
            tuple(warnings),
        )

    async def _probe_reconciliation_and_receipt(
        self,
        database: OperationalDatabaseSnapshot,
    ) -> tuple[OperationalReconciliationSnapshot, OperationalCompileReceiptSnapshot]:
        """Probe memory reconciliation status and latest compile receipt.

        Args:
            database: Current database reachability snapshot.

        Returns:
            Tuple of memory reconciliation and compile-receipt snapshots.
        """
        reconciliation = reconciliation_snapshot(
            None, configured=self._reconciliation_service is not None, reachable=False
        )
        if self._reconciliation_service is not None and database.reachable:
            try:
                diagnostics = await self._reconciliation_service.snapshot()
                reconciliation = reconciliation_snapshot(diagnostics, configured=True)
            except MemoryContextDomainError, OSError, SQLAlchemyError:
                pass
        try:
            raw_receipt = await self._obsidian_service.latest_compile_receipt()
            compile_receipt = compile_receipt_snapshot(
                raw_receipt,
                required=self._compile_receipt_required,
                expected_policy_version=self._expected_compile_policy_version,
                expected_plan_fingerprint=self._expected_compile_plan_fingerprint,
            )
        except AttributeError:
            compile_receipt = compile_receipt_snapshot(
                None, required=self._compile_receipt_required
            )
        except ObsidianDomainError, OSError, TypeError, ValueError:
            compile_receipt = OperationalCompileReceiptSnapshot(
                required=self._compile_receipt_required,
                status=CompileReceiptStatus.INVALID,
                blockers=(_WarnCode.COMPILE_RECEIPT_INVALID.value,),
            )
        return reconciliation, compile_receipt
