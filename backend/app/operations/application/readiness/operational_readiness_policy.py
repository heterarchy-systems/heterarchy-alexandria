"""Snapshot mapping and readiness classification policy."""

from __future__ import annotations

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.operations.domain.entities.operational_readiness import (
    OperationalDatabaseSnapshot,
    OperationalGraphSnapshot,
    OperationalRagSnapshot,
    OperationalReconciliationSnapshot,
    OperationalVaultSnapshot,
)
from app.operations.domain.entities.operational_retrieval_canary import (
    OperationalRetrievalCanarySnapshot,
)
from app.operations.domain.entities.operational_runtime_provenance import (
    OperationalRuntimeProvenanceSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)


def _vault_snapshot(status: ObsidianVaultStatus) -> OperationalVaultSnapshot:
    """Execute vault snapshot.

    Args:
        status: Status value used by this operation.

    Returns:
        OperationalVaultSnapshot result produced by vault snapshot.
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
    """Map an existing graph status report without asserting freshness."""
    if status is None:
        return OperationalGraphSnapshot(
            status="unknown",
            enabled=False,
            node_count=None,
            edge_count=None,
            run_id=None,
            projection_revision=None,
            warnings=("graph_projection_unchecked",),
        )
    status_value = status.status
    enabled = status.enabled
    run_id = status.run_id
    projection_version = status.projection_version
    projection_revision = (
        None if projection_version is None else str(projection_version)
    )
    warnings = ("graph_projection_status_error",) if status.errors else ()
    return OperationalGraphSnapshot(
        status=str(status_value),
        enabled=enabled,
        node_count=status.node_count,
        edge_count=status.edge_count,
        run_id=run_id,
        projection_revision=projection_revision,
        warnings=warnings,
    )


def _rag_snapshot(health: RagDependencyHealth) -> OperationalRagSnapshot:
    """Execute rag snapshot.

    Args:
        health: Health used by this operation.

    Returns:
        OperationalRagSnapshot result produced by rag snapshot.
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


def _reconciliation_snapshot(
    diagnostics: MemoryReconciliationDiagnostics | None,
    configured: bool,
    reachable: bool = True,
) -> OperationalReconciliationSnapshot:
    """Execute reconciliation snapshot.

    Args:
        diagnostics: Diagnostics used by this operation.
        configured: Configured used by this operation.
        reachable: Reachable used by this operation.

    Returns:
        OperationalReconciliationSnapshot result produced by reconciliation snapshot.
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


def _warnings(
    database: OperationalDatabaseSnapshot,
    vault: OperationalVaultSnapshot,
    rag: OperationalRagSnapshot,
    runtime: OperationalRuntimeProvenanceSnapshot,
    retrieval_canary: OperationalRetrievalCanarySnapshot,
    projection_integrity: ContextProjectionIntegritySnapshot,
    reconciliation: OperationalReconciliationSnapshot,
) -> list[str]:
    """Execute warnings.

    Args:
        database: Database used by this operation.
        vault: Vault used by this operation.
        rag: Rag used by this operation.
        runtime: Runtime build provenance used by this operation.
        retrieval_canary: Real retrieval-path canary results.
        projection_integrity: Persisted full Obsidian-to-Context projection state.
        reconciliation: Reconciliation used by this operation.

    Returns:
        list[str] result produced by warnings.
    """
    warnings: list[str] = []
    if not database.reachable:
        warnings.append("database_unreachable")
    elif database.integrity != "HEALTHY":
        warnings.append("database_integrity_not_healthy")
    if not vault.exists:
        warnings.append("vault_not_found")
    if not vault.alexandria_root_exists:
        warnings.append("alexandria_root_not_found")
    if vault.stale_notes is not None and vault.stale_notes > 0:
        warnings.append("obsidian_stale_notes_present")
    if vault.error_notes is not None and vault.error_notes > 0:
        warnings.append("obsidian_error_notes_present")
    if rag.fts is not RagHealthState.HEALTHY:
        warnings.append("rag_fts_not_healthy")
    if rag.vector is not RagHealthState.HEALTHY:
        warnings.append("rag_vector_not_healthy")
    if rag.embedding is RagHealthState.REINDEX_REQUIRED:
        warnings.append("rag_embedding_reindex_required")
    elif rag.embedding is not RagHealthState.HEALTHY:
        warnings.append("rag_embedding_not_healthy")
    if (
        rag.fts is RagHealthState.HEALTHY
        and rag.vector is RagHealthState.HEALTHY
        and rag.embedding is RagHealthState.HEALTHY
        and rag.effective_strategy is not RagStrategy.HYBRID
    ):
        warnings.append("rag_default_strategy_not_hybrid")
    if (
        rag.fts is RagHealthState.HEALTHY
        and rag.vector is RagHealthState.HEALTHY
        and rag.embedding is RagHealthState.HEALTHY
        and rag.warnings
    ):
        warnings.append("rag_status_warnings_present")
    if reconciliation.configured and not reconciliation.reachable:
        warnings.append("memory_reconciliation_repository_unreachable")
    if reconciliation.missing_temporal_states > 0:
        warnings.append("memory_reconciliation_temporal_backfill_required")
    if reconciliation.pending_review_plans > 0:
        warnings.append("memory_reconciliation_review_required")
    if reconciliation.open_conflicts > 0:
        warnings.append("memory_reconciliation_open_conflicts")
    if reconciliation.reviewing_conflicts > 0:
        warnings.append("memory_reconciliation_reviews_in_progress")
    if reconciliation.partial_apply_results > 0:
        warnings.append("memory_reconciliation_partial_apply_present")
    if reconciliation.failed_results > 0:
        warnings.append("memory_reconciliation_failed_results_present")
    if reconciliation.hard_delete_results > 0:
        warnings.append("memory_reconciliation_hard_delete_detected")
    if runtime.checked:
        warnings.extend(
            warning
            for warning in runtime.warnings
            if warning
            not in {
                "runtime_provenance_unverified",
                "runtime_revision_unverified",
                "native_revision_unverified",
            }
        )
    if retrieval_canary.checked:
        if not retrieval_canary.fts.ok:
            warnings.append("retrieval_canary_fts_only_failed")
        if not retrieval_canary.vector.ok:
            warnings.append("retrieval_canary_vector_only_failed")
        if not retrieval_canary.hybrid.ok:
            warnings.append("retrieval_canary_hybrid_failed")
    if projection_integrity.checked:
        if not projection_integrity.available:
            warnings.append("projection_integrity_snapshot_missing")
        elif projection_integrity.invalid_count > 0:
            warnings.append("projection_integrity_invalid_notes")
        if (
            projection_integrity.available
            and projection_integrity.source_revision
            != projection_integrity.current_source_revision
        ):
            warnings.append("projection_integrity_source_revision_mismatch")
        elif projection_integrity.available and projection_integrity.stale:
            warnings.append("projection_integrity_snapshot_stale")
    return warnings


def _blockers(warnings: list[str]) -> list[str]:
    """Execute blockers.

    Args:
        warnings: Warnings used by this operation.

    Returns:
        list[str] result produced by blockers.
    """
    blocking_codes = {
        "database_unreachable",
        "database_integrity_not_healthy",
        "vault_not_found",
        "alexandria_root_not_found",
        "obsidian_stale_notes_present",
        "obsidian_error_notes_present",
        "rag_fts_not_healthy",
        "rag_default_strategy_not_hybrid",
        "rag_status_warnings_present",
        "recovery_in_progress",
        "memory_reconciliation_repository_unreachable",
        "memory_reconciliation_partial_apply_present",
        "memory_reconciliation_failed_results_present",
        "memory_reconciliation_hard_delete_detected",
        "runtime_expected_revision_missing",
        "runtime_revision_missing",
        "runtime_revision_mismatch",
        "native_provenance_unavailable",
        "native_revision_missing",
        "native_revision_mismatch",
        "native_feature_authority_schema_mismatch",
        "retrieval_canary_fts_only_failed",
        "retrieval_canary_vector_only_failed",
        "retrieval_canary_hybrid_failed",
        "projection_integrity_snapshot_missing",
        "projection_integrity_snapshot_stale",
        "projection_integrity_source_revision_mismatch",
        "projection_integrity_invalid_notes",
    }
    return [warning for warning in warnings if warning in blocking_codes]


def _status(
    database: OperationalDatabaseSnapshot,
    vault: OperationalVaultSnapshot,
    rag: OperationalRagSnapshot,
    warnings: list[str],
    active_recovery_run_id: str | None,
) -> OperationalReadinessStatus:
    """Execute status.

    Args:
        database: Database used by this operation.
        vault: Vault used by this operation.
        rag: Rag used by this operation.
        warnings: Warnings used by this operation.
        active_recovery_run_id: Identifier for active recovery run.

    Returns:
        OperationalReadinessStatus result produced by status.
    """
    if active_recovery_run_id is not None:
        return OperationalReadinessStatus.RECOVERING
    warning_set = set(warnings)
    if warning_set & {
        "runtime_expected_revision_missing",
        "runtime_revision_missing",
        "runtime_revision_mismatch",
        "native_provenance_unavailable",
        "native_revision_missing",
        "native_revision_mismatch",
        "native_feature_authority_schema_mismatch",
    }:
        return OperationalReadinessStatus.DEGRADED_RUNTIME_DRIFT
    if warning_set & {
        "retrieval_canary_fts_only_failed",
        "retrieval_canary_vector_only_failed",
        "retrieval_canary_hybrid_failed",
    }:
        return OperationalReadinessStatus.DEGRADED_RETRIEVAL_CANARY
    if warning_set & {
        "projection_integrity_snapshot_missing",
        "projection_integrity_snapshot_stale",
        "projection_integrity_source_revision_mismatch",
        "projection_integrity_invalid_notes",
    }:
        return OperationalReadinessStatus.DEGRADED_PROJECTION_INTEGRITY
    blockers = _blockers(warnings)
    if blockers:
        return OperationalReadinessStatus.BLOCKED
    if (
        rag.fts is RagHealthState.HEALTHY
        and rag.effective_strategy is RagStrategy.FTS_ONLY
        and (
            rag.vector is not RagHealthState.HEALTHY
            or rag.embedding is not RagHealthState.HEALTHY
        )
    ):
        return OperationalReadinessStatus.DEGRADED_FTS_ONLY
    if warnings:
        return OperationalReadinessStatus.UNKNOWN
    return OperationalReadinessStatus.READY


def _next_actions(
    warnings: list[str],
    index_errors: tuple[ObsidianIndexError, ...] = (),
) -> list[str]:
    """Execute next actions.

    Args:
        warnings: Warnings used by this operation.
        index_errors: Index errors used by this operation.

    Returns:
        list[str] result produced by next actions.
    """
    actions: list[str] = []
    warning_set = set(warnings)
    if {"vault_not_found", "alexandria_root_not_found"} & warning_set:
        actions.append("inspect_vault_configuration")
    if "obsidian_stale_notes_present" in warning_set:
        actions.append("reindex_vault")
    if "obsidian_error_notes_present" in warning_set:
        actions.extend(_index_error_actions(index_errors))
    if {
        "rag_vector_not_healthy",
        "rag_embedding_reindex_required",
        "rag_embedding_not_healthy",
        "rag_default_strategy_not_hybrid",
        "rag_status_warnings_present",
    } & warning_set:
        actions.append("reindex_embeddings")
    if "database_unreachable" in warning_set:
        actions.append("inspect_database")
    if "recovery_in_progress" in warning_set:
        actions.append("inspect_recovery_run")
    if "memory_reconciliation_repository_unreachable" in warning_set:
        actions.append("inspect_memory_reconciliation_repository")
    if "memory_reconciliation_temporal_backfill_required" in warning_set:
        actions.append("preview_existing_memory_reconciliation")
    if {
        "memory_reconciliation_review_required",
        "memory_reconciliation_open_conflicts",
        "memory_reconciliation_reviews_in_progress",
    } & warning_set:
        actions.append("review_memory_reconciliation")
    if {
        "memory_reconciliation_partial_apply_present",
        "memory_reconciliation_failed_results_present",
    } & warning_set:
        actions.append("inspect_memory_reconciliation_failures")
    if "memory_reconciliation_hard_delete_detected" in warning_set:
        actions.append("audit_memory_reconciliation_integrity")
    if warning_set & {
        "runtime_expected_revision_missing",
        "runtime_revision_missing",
        "runtime_revision_mismatch",
        "native_provenance_unavailable",
        "native_revision_missing",
        "native_revision_mismatch",
        "native_feature_authority_schema_mismatch",
    }:
        actions.append("rebuild_and_redeploy_runtime")
    if warning_set & {
        "retrieval_canary_fts_only_failed",
        "retrieval_canary_vector_only_failed",
        "retrieval_canary_hybrid_failed",
    }:
        actions.append("inspect_retrieval_canary")
    if warning_set & {
        "projection_integrity_snapshot_missing",
        "projection_integrity_snapshot_stale",
        "projection_integrity_source_revision_mismatch",
        "projection_integrity_invalid_notes",
    }:
        actions.append("refresh_projection_integrity")
    return actions


def _index_error_actions(
    index_errors: tuple[ObsidianIndexError, ...],
) -> list[str]:
    """Execute index error actions.

    Args:
        index_errors: Index errors used by this operation.

    Returns:
        list[str] result produced by index error actions.
    """
    if not index_errors:
        return ["inspect_obsidian_index_errors"]
    codes = {error.error_code for error in index_errors}
    actions: list[str] = []
    if ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED in codes:
        actions.append("review_obsidian_frontmatter_security_errors")
    if codes & {
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
    }:
        actions.append("resolve_duplicate_context_identity")
    if ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION in codes:
        actions.append("inspect_obsidian_path_security")
    if ObsidianIndexErrorCode.SOURCE_READ_FAILED in codes:
        actions.append("inspect_obsidian_source_storage")
    if ObsidianIndexErrorCode.INDEX_WRITE_FAILED in codes:
        actions.append("inspect_obsidian_index_storage")
    repairable = codes - {
        ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
        ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION,
        ObsidianIndexErrorCode.SOURCE_READ_FAILED,
        ObsidianIndexErrorCode.INDEX_WRITE_FAILED,
    }
    if repairable:
        actions.append("plan_index_error_repairs")
    return actions or ["inspect_obsidian_index_errors"]
