"""Memory Steward diagnose and seal orchestration services.

Compose existing authoritative primitives (readiness, maintenance queue,
Memory Compacts) into bounded operational workflows without creating a
second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.entities.maintenance_job import MaintenanceQueueSnapshot
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.event_enum.memory_steward_enums import MemoryStewardStatus
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)

_CURRENT_COMPACT_EVIDENCE_LIMIT = 200


class CurrentCompactsReadPort(Protocol):
    """Read-only Memory Compact evidence used by steward workflows."""

    async def list_compacts(
        self,
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        covered_after: datetime | None = None,
        covered_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryCompact], int]:
        """Return one bounded page of Memory Compacts and the total count."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StewardDiagnostic:
    """One actionable diagnostic with a detail operation reference."""

    code: str
    blocking: bool
    count: int
    detail_operation: str
    recommended_operation: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StewardCurrentCompactsEvidence:
    """CURRENT Memory Compact evidence evaluated over a bounded page."""

    count: int
    unique_projects: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class StewardDiagnoseResult:
    """Memory Steward diagnose result composing all diagnostic evidence."""

    overall_status: MemoryStewardStatus
    diagnostics: tuple[StewardDiagnostic, ...]
    readiness: OperationalReadinessSnapshot
    queue: MaintenanceQueueSnapshot | None = None
    current_compacts: StewardCurrentCompactsEvidence | None = None


def _diagnose_from_readiness(
    snapshot: OperationalReadinessSnapshot,
) -> list[StewardDiagnostic]:
    """Derive steward diagnostics from one readiness snapshot.

    Args:
        snapshot: Readiness snapshot from the operational service.

    Returns:
        Ordered diagnostics with detail operation references.
    """
    diagnostics: list[StewardDiagnostic] = []
    vault = snapshot.vault
    if (vault.stale_notes or 0) > 0:
        diagnostics.append(
            StewardDiagnostic(
                code="VAULT_STALE_NOTES",
                blocking=False,
                count=vault.stale_notes or 0,
                detail_operation="alexandria_read_note_raw",
                recommended_operation="alexandria_reindex_vault",
            )
        )
    if (vault.error_notes or 0) > 0:
        diagnostics.append(
            StewardDiagnostic(
                code="VAULT_ERROR_NOTES",
                blocking=True,
                count=vault.error_notes or 0,
                detail_operation="alexandria_read_note_raw",
                recommended_operation="alexandria_recover",
            )
        )
    rag = snapshot.rag
    if rag.fts != "HEALTHY":
        diagnostics.append(
            StewardDiagnostic(
                code="RAG_FTS_UNHEALTHY",
                blocking=False,
                count=1,
                detail_operation="alexandria_operational_readiness",
                recommended_operation="alexandria_reindex_vault",
            )
        )
    if rag.vector == "REINDEX_REQUIRED":
        diagnostics.append(
            StewardDiagnostic(
                code="RAG_VECTOR_REINDEX_REQUIRED",
                blocking=False,
                count=1,
                detail_operation="alexandria_operational_readiness",
                recommended_operation="alexandria_memory_steward_seal",
            )
        )
    graph = snapshot.graph
    if graph.enabled and graph.last_run_issue_total > 0:
        diagnostics.append(
            StewardDiagnostic(
                code="GRAPH_ISSUES",
                blocking=False,
                count=graph.last_run_issue_total,
                detail_operation="alexandria_graph_list_issues",
                recommended_operation="alexandria_rebuild_graph_projection",
            )
        )
    for warning in snapshot.warnings:
        if "database" in warning.lower():
            diagnostics.append(
                StewardDiagnostic(
                    code="DATABASE_UNREACHABLE",
                    blocking=True,
                    count=1,
                    detail_operation="alexandria_operational_readiness",
                    recommended_operation="alexandria_recover",
                )
            )
            break
    return diagnostics


async def _gather_queue_evidence(
    maintenance_queue: MaintenanceJobSubmitter | None,
    diagnostics: list[StewardDiagnostic],
) -> MaintenanceQueueSnapshot | None:
    """Append queue diagnostics and return the queue evidence snapshot.

    Args:
        maintenance_queue: Optional maintenance queue submission port.
        diagnostics: Diagnostic list the evidence gathering appends to.

    Returns:
        Aggregate queue snapshot, or None when queueing is disabled or
        unavailable.
    """
    if maintenance_queue is None:
        return None
    try:
        snapshot = await maintenance_queue.queue_status()
    except MaintenanceQueueUnavailableError:
        diagnostics.append(
            StewardDiagnostic(
                code="QUEUE_UNAVAILABLE",
                blocking=False,
                count=1,
                detail_operation="alexandria_get_maintenance_queue_status",
                recommended_operation="alexandria_get_maintenance_queue_status",
            )
        )
        return None
    if snapshot.dead_letter_length > 0:
        diagnostics.append(
            StewardDiagnostic(
                code="DLQ_RESIDUALS",
                blocking=False,
                count=snapshot.dead_letter_length,
                detail_operation="alexandria_list_maintenance_dead_letters",
                recommended_operation="alexandria_list_maintenance_dead_letters",
            )
        )
    return snapshot


async def _gather_current_compacts_evidence(
    compact_port: CurrentCompactsReadPort | None,
) -> StewardCurrentCompactsEvidence | None:
    """Return bounded CURRENT Memory Compact evidence, or None on failure.

    Args:
        compact_port: Optional Memory Compact read port.

    Returns:
        Compact count with project uniqueness evaluated over at most
        200 rows, or None when the evidence is unavailable.
    """
    if compact_port is None:
        return None
    try:
        page, total = await compact_port.list_compacts(
            status=MemoryCompactStatus.CURRENT,
            limit=_CURRENT_COMPACT_EVIDENCE_LIMIT,
        )
    except (SQLAlchemyError, OSError, ValueError):
        return None
    projects = {compact.project for compact in page}
    return StewardCurrentCompactsEvidence(
        count=total,
        unique_projects=len(projects) == len(page),
    )


async def _gather_evidence(
    readiness_service: OperationalReadinessService,
    maintenance_queue: MaintenanceJobSubmitter | None,
    compact_port: CurrentCompactsReadPort | None,
) -> tuple[
    OperationalReadinessSnapshot,
    list[StewardDiagnostic],
    MaintenanceQueueSnapshot | None,
    StewardCurrentCompactsEvidence | None,
]:
    """Compose every steward evidence source into one bundle.

    Args:
        readiness_service: Operational readiness service.
        maintenance_queue: Optional maintenance queue submission port.
        compact_port: Optional Memory Compact read port.

    Returns:
        Readiness snapshot with derived diagnostics and optional queue
        and CURRENT compact evidence.
    """
    snapshot = await readiness_service.snapshot()
    diagnostics = _diagnose_from_readiness(snapshot)
    queue = await _gather_queue_evidence(maintenance_queue, diagnostics)
    current_compacts = await _gather_current_compacts_evidence(compact_port)
    return snapshot, diagnostics, queue, current_compacts


class MemoryStewardDiagnoseService:
    """Compose readiness evidence into Memory Steward diagnostics."""

    def __init__(
        self,
        readiness_service: OperationalReadinessService,
        maintenance_queue: MaintenanceJobSubmitter | None = None,
        compact_port: CurrentCompactsReadPort | None = None,
    ) -> None:
        """Create the diagnose service.

        Args:
            readiness_service: Operational readiness service.
            maintenance_queue: Optional maintenance queue evidence port.
            compact_port: Optional Memory Compact read port.
        """
        self._readiness_service = readiness_service
        self._maintenance_queue = maintenance_queue
        self._compact_port = compact_port

    async def diagnose(self) -> StewardDiagnoseResult:
        """Compose readiness evidence into actionable diagnostics.

        Returns:
            Diagnose result with overall status and per-issue detail refs.
        """
        snapshot, diagnostics, queue, current_compacts = await _gather_evidence(
            self._readiness_service,
            self._maintenance_queue,
            self._compact_port,
        )
        if snapshot.status is OperationalReadinessStatus.READY or snapshot.ready:
            overall = MemoryStewardStatus.READY
        elif snapshot.blockers:
            overall = MemoryStewardStatus.NOT_READY
        else:
            overall = MemoryStewardStatus.DEGRADED
        return StewardDiagnoseResult(
            overall_status=overall,
            diagnostics=tuple(diagnostics),
            readiness=snapshot,
            queue=queue,
            current_compacts=current_compacts,
        )


class MemoryStewardSealService:
    """Bounded seal orchestration composing authoritative primitives."""

    def __init__(
        self,
        readiness_service: OperationalReadinessService,
        maintenance_queue: MaintenanceJobSubmitter | None = None,
        compact_port: CurrentCompactsReadPort | None = None,
    ) -> None:
        """Create the seal service.

        Args:
            readiness_service: Operational readiness service.
            maintenance_queue: Optional maintenance queue evidence port.
            compact_port: Optional Memory Compact read port.
        """
        self._readiness_service = readiness_service
        self._maintenance_queue = maintenance_queue
        self._compact_port = compact_port

    async def seal(self) -> StewardDiagnoseResult:
        """Run the final readiness verification for one memory circulation.

        Composes the existing authoritative operations (reindex, embedding
        recovery, graph rebuild) that were already executed by the caller.
        This service only verifies the final state and reports residuals.

        Returns:
            Seal result with overall status and residual diagnostics.
        """
        snapshot, diagnostics, queue, current_compacts = await _gather_evidence(
            self._readiness_service,
            self._maintenance_queue,
            self._compact_port,
        )
        blocking = [d for d in diagnostics if d.blocking]
        if snapshot.database.reachable is False:
            status = MemoryStewardStatus.FAILED
        elif blocking:
            status = MemoryStewardStatus.NOT_READY
        elif diagnostics:
            status = MemoryStewardStatus.READY_WITH_RESIDUALS
        else:
            status = MemoryStewardStatus.READY
        return StewardDiagnoseResult(
            overall_status=status,
            diagnostics=tuple(diagnostics),
            readiness=snapshot,
            queue=queue,
            current_compacts=current_compacts,
        )
