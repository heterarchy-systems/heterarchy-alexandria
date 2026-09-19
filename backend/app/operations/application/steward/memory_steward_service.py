"""Memory Steward diagnose and seal orchestration services.

Compose existing authoritative primitives (readiness, reindex, embedding
recovery, graph diagnostics) into bounded operational workflows without
creating a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class StewardDiagnostic:
    """One actionable diagnostic with a detail operation reference."""

    code: str
    blocking: bool
    count: int
    detail_operation: str
    recommended_operation: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StewardDiagnoseResult:
    """Memory Steward diagnose result composing all diagnostic evidence."""

    overall_status: str
    diagnostics: tuple[StewardDiagnostic, ...]
    readiness: OperationalReadinessSnapshot


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


class MemoryStewardDiagnoseService:
    """Compose readiness evidence into Memory Steward diagnostics."""

    def __init__(self, readiness_service: OperationalReadinessService) -> None:
        """Create the diagnose service.

        Args:
            readiness_service: Operational readiness service.
        """
        self._readiness_service = readiness_service

    async def diagnose(self) -> StewardDiagnoseResult:
        """Compose readiness evidence into actionable diagnostics.

        Returns:
            Diagnose result with overall status and per-issue detail refs.
        """
        snapshot = await self._readiness_service.snapshot()
        diagnostics = _diagnose_from_readiness(snapshot)
        if snapshot.status.value in {"READY", "READY_WITH_RESIDUALS"}:
            overall = snapshot.status.value
        elif snapshot.ready:
            overall = "READY"
        elif snapshot.blockers:
            overall = "NOT_READY"
        else:
            overall = "DEGRADED"
        return StewardDiagnoseResult(
            overall_status=overall,
            diagnostics=tuple(diagnostics),
            readiness=snapshot,
        )


class MemoryStewardSealService:
    """Bounded seal orchestration composing authoritative primitives."""

    def __init__(
        self,
        readiness_service: OperationalReadinessService,
    ) -> None:
        """Create the seal service.

        Args:
            readiness_service: Operational readiness service.
        """
        self._readiness_service = readiness_service

    async def seal(self) -> StewardDiagnoseResult:
        """Run the final readiness verification for one memory circulation.

        Composes the existing authoritative operations (reindex, embedding
        recovery, graph rebuild) that were already executed by the caller.
        This service only verifies the final state and reports residuals.

        Returns:
            Seal result with overall status and residual diagnostics.
        """
        snapshot = await self._readiness_service.snapshot()
        diagnostics = _diagnose_from_readiness(snapshot)
        blocking = [d for d in diagnostics if d.blocking]
        if snapshot.database.reachable is False:
            status = "FAILED"
        elif blocking:
            status = "NOT_READY"
        elif diagnostics:
            status = "READY_WITH_RESIDUALS"
        else:
            status = "READY"
        return StewardDiagnoseResult(
            overall_status=status,
            diagnostics=tuple(diagnostics),
            readiness=snapshot,
        )
