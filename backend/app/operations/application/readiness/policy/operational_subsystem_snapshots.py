"""Subsystem snapshot mappers for operational readiness probing."""

from __future__ import annotations

from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.domain.entities.operational_readiness import (
    OperationalGraphSnapshot,
    OperationalRagSnapshot,
    OperationalReconciliationSnapshot,
    OperationalVaultSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalGraphProjectionStatus,
    OperationalReadinessNextAction as _NextAction,
    OperationalReadinessWarningCode as _WarnCode,
)


def vault_snapshot(status: ObsidianVaultStatus) -> OperationalVaultSnapshot:
    """Project an Obsidian vault status into an operational readiness snapshot.

    Args:
        status: Current Obsidian vault status.

    Returns:
        Operational vault readiness snapshot.
    """
    return OperationalVaultSnapshot(
        exists=status.vault_exists,
        readable=status.vault_exists and status.alexandria_root_exists,
        vault_path=status.vault_path,
        alexandria_root=status.alexandria_root,
        alexandria_root_exists=status.alexandria_root_exists,
        indexed_notes=status.indexed_notes,
        stale_notes=status.stale_notes,
        error_notes=status.error_notes,
    )


def graph_snapshot_from_status(
    status: ObsidianGraphProjectionStatusReport | None,
) -> OperationalGraphSnapshot:
    """Map an existing graph status report without asserting freshness.

    Args:
        status: Persisted graph projection status report, or None if unchecked.

    Returns:
        Operational graph readiness snapshot.
    """
    if status is None:
        return OperationalGraphSnapshot(
            status=OperationalGraphProjectionStatus.UNKNOWN.value,
            enabled=False,
            node_count=None,
            edge_count=None,
            run_id=None,
            projection_revision=None,
            warnings=(_WarnCode.GRAPH_PROJECTION_UNCHECKED.value,),
        )
    status_value = status.status
    enabled = status.enabled
    run_id = status.run_id
    projection_version = status.projection_version
    projection_revision = (
        None if projection_version is None else str(projection_version)
    )
    warnings = (_WarnCode.GRAPH_PROJECTION_STATUS_ERROR.value,) if status.errors else ()
    issue_total = status.last_run_issue_total
    return OperationalGraphSnapshot(
        status=str(status_value),
        enabled=enabled,
        node_count=status.node_count,
        edge_count=status.edge_count,
        run_id=run_id,
        projection_revision=projection_revision,
        warnings=warnings,
        recommended_operation=(
            _NextAction.ALEXANDRIA_GRAPH_LIST_ISSUES.value if issue_total > 0 else None
        ),
        last_run_issue_total=issue_total,
    )


def rag_snapshot(health: RagDependencyHealth) -> OperationalRagSnapshot:
    """Project RAG dependency health into an operational readiness snapshot.

    Args:
        health: RAG dependency health state.

    Returns:
        Operational RAG readiness snapshot.
    """
    return OperationalRagSnapshot(
        fts=health.fts,
        vector=health.vector,
        embedding=health.embedding,
        effective_strategy=health.default_strategy,
        model_name=health.model_name,
        dimensions=health.dimensions,
        fingerprint=health.fingerprint,
        source_statuses=tuple(health.source_statuses),
        warnings=tuple(health.warnings),
    )


def reconciliation_snapshot(
    diagnostics: MemoryReconciliationDiagnostics | None,
    configured: bool,
    reachable: bool = True,
) -> OperationalReconciliationSnapshot:
    """Project memory reconciliation diagnostics into a readiness snapshot.

    Args:
        diagnostics: Memory reconciliation diagnostics, if available.
        configured: Whether reconciliation is configured.
        reachable: Whether the reconciliation repository is reachable.

    Returns:
        Operational reconciliation readiness snapshot.
    """
    if diagnostics is None:
        return OperationalReconciliationSnapshot(
            configured=configured,
            reachable=reachable,
            total_contexts=0,
            temporal_state_count=0,
            missing_temporal_states=0,
            backfill_complete=False,
            total_plans=0,
            pending_review_plans=0,
            total_results=0,
            partial_apply_results=0,
            failed_results=0,
            open_conflicts=0,
            reviewing_conflicts=0,
            hard_delete_results=0,
            latest_failure_code=None,
            latest_failure_at=None,
        )
    return OperationalReconciliationSnapshot(
        configured=True,
        reachable=diagnostics.reachable,
        total_contexts=diagnostics.total_contexts,
        temporal_state_count=diagnostics.temporal_state_count,
        missing_temporal_states=diagnostics.missing_temporal_states,
        backfill_complete=diagnostics.missing_temporal_states == 0,
        total_plans=diagnostics.total_plans,
        pending_review_plans=diagnostics.pending_review_plans,
        total_results=diagnostics.total_results,
        partial_apply_results=diagnostics.partial_apply_results,
        failed_results=diagnostics.failed_results,
        open_conflicts=diagnostics.open_conflicts,
        reviewing_conflicts=diagnostics.reviewing_conflicts,
        hard_delete_results=diagnostics.hard_delete_results,
        latest_failure_code=diagnostics.latest_failure_code,
        latest_failure_at=diagnostics.latest_failure_at,
    )
