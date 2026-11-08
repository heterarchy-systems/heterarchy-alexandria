"""Warning collection, blocker filtering, and readiness classification policy."""

from __future__ import annotations

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianIndexError
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.operations.application.readiness.policy.operational_subsystem_snapshots import (
    graph_snapshot_from_status,
    rag_snapshot,
    reconciliation_snapshot,
    vault_snapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalDatabaseSnapshot,
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
    OperationalReadinessNextAction as _NextAction,
    OperationalReadinessStatus,
    OperationalReadinessWarningCode as _WarnCode,
)

__all__ = (
    "graph_snapshot_from_status",
    "next_actions",
    "rag_snapshot",
    "readiness_blockers",
    "readiness_status",
    "readiness_warnings",
    "reconciliation_snapshot",
    "vault_snapshot",
)

_UNVERIFIED_RUNTIME_WARNINGS = frozenset(
    {
        _WarnCode.RUNTIME_PROVENANCE_UNVERIFIED.value,
        _WarnCode.RUNTIME_REVISION_UNVERIFIED.value,
        _WarnCode.NATIVE_REVISION_UNVERIFIED.value,
    }
)
_RUNTIME_DRIFT_WARNINGS = frozenset(
    {
        _WarnCode.RUNTIME_EXPECTED_REVISION_MISSING.value,
        _WarnCode.RUNTIME_REVISION_MISSING.value,
        _WarnCode.RUNTIME_REVISION_MISMATCH.value,
        _WarnCode.NATIVE_PROVENANCE_UNAVAILABLE.value,
        _WarnCode.NATIVE_REVISION_MISSING.value,
        _WarnCode.NATIVE_REVISION_MISMATCH.value,
        _WarnCode.NATIVE_FEATURE_AUTHORITY_SCHEMA_MISMATCH.value,
    }
)
_RETRIEVAL_CANARY_WARNINGS = frozenset(
    {
        _WarnCode.RETRIEVAL_CANARY_FTS_ONLY_FAILED.value,
        _WarnCode.RETRIEVAL_CANARY_VECTOR_ONLY_FAILED.value,
        _WarnCode.RETRIEVAL_CANARY_HYBRID_FAILED.value,
    }
)
_PROJECTION_INTEGRITY_WARNINGS = frozenset(
    {
        _WarnCode.PROJECTION_INTEGRITY_SNAPSHOT_MISSING.value,
        _WarnCode.PROJECTION_INTEGRITY_SNAPSHOT_STALE.value,
        _WarnCode.PROJECTION_INTEGRITY_SOURCE_REVISION_MISMATCH.value,
        _WarnCode.PROJECTION_INTEGRITY_INVALID_NOTES.value,
    }
)
_BLOCKING_WARNING_CODES = (
    frozenset(
        {
            _WarnCode.COMPILE_RECEIPT_REQUIRED.value,
            _WarnCode.COMPILE_RECEIPT_INVALID.value,
            _WarnCode.COMPILE_RECEIPT_STALE.value,
            _WarnCode.DATABASE_UNREACHABLE.value,
            _WarnCode.DATABASE_INTEGRITY_NOT_HEALTHY.value,
            _WarnCode.VAULT_NOT_FOUND.value,
            _WarnCode.ALEXANDRIA_ROOT_NOT_FOUND.value,
            _WarnCode.OBSIDIAN_STALE_NOTES_PRESENT.value,
            _WarnCode.OBSIDIAN_ERROR_NOTES_PRESENT.value,
            _WarnCode.RAG_FTS_NOT_HEALTHY.value,
            _WarnCode.RAG_DEFAULT_STRATEGY_NOT_HYBRID.value,
            _WarnCode.RAG_STATUS_WARNINGS_PRESENT.value,
            _WarnCode.RECOVERY_IN_PROGRESS.value,
            _WarnCode.MEMORY_RECONCILIATION_REPOSITORY_UNREACHABLE.value,
            _WarnCode.MEMORY_RECONCILIATION_PARTIAL_APPLY_PRESENT.value,
            _WarnCode.MEMORY_RECONCILIATION_FAILED_RESULTS_PRESENT.value,
            _WarnCode.MEMORY_RECONCILIATION_HARD_DELETE_DETECTED.value,
        }
    )
    | _RUNTIME_DRIFT_WARNINGS
    | _RETRIEVAL_CANARY_WARNINGS
    | _PROJECTION_INTEGRITY_WARNINGS
)


def readiness_warnings(
    database: OperationalDatabaseSnapshot,
    vault: OperationalVaultSnapshot,
    rag: OperationalRagSnapshot,
    runtime: OperationalRuntimeProvenanceSnapshot,
    retrieval_canary: OperationalRetrievalCanarySnapshot,
    projection_integrity: ContextProjectionIntegritySnapshot,
    reconciliation: OperationalReconciliationSnapshot,
) -> list[str]:
    """Collect readiness warning codes across subsystem snapshots.

    Args:
        database: Database readiness snapshot.
        vault: Vault readiness snapshot.
        rag: RAG readiness snapshot.
        runtime: Runtime build provenance snapshot.
        retrieval_canary: Retrieval canary snapshot.
        projection_integrity: Persisted Obsidian-to-Context projection state.
        reconciliation: Memory reconciliation snapshot.

    Returns:
        Ordered list of warning code strings.
    """
    warnings: list[str] = []
    if not database.reachable:
        warnings.append(_WarnCode.DATABASE_UNREACHABLE.value)
    elif database.integrity != "HEALTHY":
        warnings.append(_WarnCode.DATABASE_INTEGRITY_NOT_HEALTHY.value)
    if not vault.exists:
        warnings.append(_WarnCode.VAULT_NOT_FOUND.value)
    if not vault.alexandria_root_exists:
        warnings.append(_WarnCode.ALEXANDRIA_ROOT_NOT_FOUND.value)
    if vault.stale_notes is not None and vault.stale_notes > 0:
        warnings.append(_WarnCode.OBSIDIAN_STALE_NOTES_PRESENT.value)
    if vault.error_notes is not None and vault.error_notes > 0:
        warnings.append(_WarnCode.OBSIDIAN_ERROR_NOTES_PRESENT.value)
    if rag.fts is not RagHealthState.HEALTHY:
        warnings.append(_WarnCode.RAG_FTS_NOT_HEALTHY.value)
    if rag.vector is not RagHealthState.HEALTHY:
        warnings.append(_WarnCode.RAG_VECTOR_NOT_HEALTHY.value)
    if rag.embedding is RagHealthState.REINDEX_REQUIRED:
        warnings.append(_WarnCode.RAG_EMBEDDING_REINDEX_REQUIRED.value)
    elif rag.embedding is not RagHealthState.HEALTHY:
        warnings.append(_WarnCode.RAG_EMBEDDING_NOT_HEALTHY.value)
    if (
        rag.fts is RagHealthState.HEALTHY
        and rag.vector is RagHealthState.HEALTHY
        and rag.embedding is RagHealthState.HEALTHY
        and rag.effective_strategy is not RagStrategy.HYBRID
    ):
        warnings.append(_WarnCode.RAG_DEFAULT_STRATEGY_NOT_HYBRID.value)
    if (
        rag.fts is RagHealthState.HEALTHY
        and rag.vector is RagHealthState.HEALTHY
        and rag.embedding is RagHealthState.HEALTHY
        and rag.warnings
    ):
        warnings.append(_WarnCode.RAG_STATUS_WARNINGS_PRESENT.value)
    if reconciliation.configured and not reconciliation.reachable:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_REPOSITORY_UNREACHABLE.value)
    if reconciliation.missing_temporal_states > 0:
        warnings.append(
            _WarnCode.MEMORY_RECONCILIATION_TEMPORAL_BACKFILL_REQUIRED.value
        )
    if reconciliation.pending_review_plans > 0:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_REVIEW_REQUIRED.value)
    if reconciliation.open_conflicts > 0:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_OPEN_CONFLICTS.value)
    if reconciliation.reviewing_conflicts > 0:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_REVIEWS_IN_PROGRESS.value)
    if reconciliation.partial_apply_results > 0:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_PARTIAL_APPLY_PRESENT.value)
    if reconciliation.failed_results > 0:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_FAILED_RESULTS_PRESENT.value)
    if reconciliation.hard_delete_results > 0:
        warnings.append(_WarnCode.MEMORY_RECONCILIATION_HARD_DELETE_DETECTED.value)
    if runtime.checked:
        warnings.extend(
            warning
            for warning in runtime.warnings
            if warning not in _UNVERIFIED_RUNTIME_WARNINGS
        )
    if retrieval_canary.checked:
        if not retrieval_canary.fts.ok:
            warnings.append(_WarnCode.RETRIEVAL_CANARY_FTS_ONLY_FAILED.value)
        if not retrieval_canary.vector.ok:
            warnings.append(_WarnCode.RETRIEVAL_CANARY_VECTOR_ONLY_FAILED.value)
        if not retrieval_canary.hybrid.ok:
            warnings.append(_WarnCode.RETRIEVAL_CANARY_HYBRID_FAILED.value)
    if projection_integrity.checked:
        if not projection_integrity.available:
            warnings.append(_WarnCode.PROJECTION_INTEGRITY_SNAPSHOT_MISSING.value)
        elif projection_integrity.invalid_count > 0:
            warnings.append(_WarnCode.PROJECTION_INTEGRITY_INVALID_NOTES.value)
        if (
            projection_integrity.available
            and projection_integrity.source_revision
            != projection_integrity.current_source_revision
        ):
            warnings.append(
                _WarnCode.PROJECTION_INTEGRITY_SOURCE_REVISION_MISMATCH.value
            )
        elif projection_integrity.available and projection_integrity.stale:
            warnings.append(_WarnCode.PROJECTION_INTEGRITY_SNAPSHOT_STALE.value)
    return warnings


def readiness_blockers(warnings: list[str]) -> list[str]:
    """Filter warning codes down to those that block operational readiness.

    Args:
        warnings: Collected readiness warning codes.

    Returns:
        Subset of warning codes that block readiness.
    """
    return [warning for warning in warnings if warning in _BLOCKING_WARNING_CODES]


def readiness_status(
    database: OperationalDatabaseSnapshot,
    vault: OperationalVaultSnapshot,
    rag: OperationalRagSnapshot,
    warnings: list[str],
    active_recovery_run_id: str | None,
) -> OperationalReadinessStatus:
    """Classify overall operational readiness status from subsystem evidence.

    Args:
        database: Database readiness snapshot.
        vault: Vault readiness snapshot.
        rag: RAG readiness snapshot.
        warnings: Collected readiness warning codes.
        active_recovery_run_id: Active recovery run identifier, if any.

    Returns:
        Classified operational readiness status.
    """
    del database, vault
    if active_recovery_run_id is not None:
        return OperationalReadinessStatus.RECOVERING
    warning_set = set(warnings)
    if warning_set & _RUNTIME_DRIFT_WARNINGS:
        return OperationalReadinessStatus.DEGRADED_RUNTIME_DRIFT
    if warning_set & _RETRIEVAL_CANARY_WARNINGS:
        return OperationalReadinessStatus.DEGRADED_RETRIEVAL_CANARY
    if warning_set & _PROJECTION_INTEGRITY_WARNINGS:
        return OperationalReadinessStatus.DEGRADED_PROJECTION_INTEGRITY
    if readiness_blockers(warnings):
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


def next_actions(
    warnings: list[str],
    index_errors: tuple[ObsidianIndexError, ...] = (),
) -> list[str]:
    """Recommend next operator actions for the given readiness warnings.

    Args:
        warnings: Collected readiness warning codes.
        index_errors: Persisted Obsidian index errors, if any.

    Returns:
        Ordered list of recommended operator actions.
    """
    actions: list[str] = []
    warning_set = set(warnings)
    if {
        _WarnCode.VAULT_NOT_FOUND.value,
        _WarnCode.ALEXANDRIA_ROOT_NOT_FOUND.value,
    } & warning_set:
        actions.append(_NextAction.INSPECT_VAULT_CONFIGURATION.value)
    if _WarnCode.OBSIDIAN_STALE_NOTES_PRESENT.value in warning_set:
        actions.append(_NextAction.REINDEX_VAULT.value)
    if _WarnCode.OBSIDIAN_ERROR_NOTES_PRESENT.value in warning_set:
        actions.extend(_index_error_actions(index_errors))
    if {
        _WarnCode.RAG_VECTOR_NOT_HEALTHY.value,
        _WarnCode.RAG_EMBEDDING_REINDEX_REQUIRED.value,
        _WarnCode.RAG_EMBEDDING_NOT_HEALTHY.value,
        _WarnCode.RAG_DEFAULT_STRATEGY_NOT_HYBRID.value,
        _WarnCode.RAG_STATUS_WARNINGS_PRESENT.value,
    } & warning_set:
        actions.append(_NextAction.REINDEX_EMBEDDINGS.value)
    if _WarnCode.DATABASE_UNREACHABLE.value in warning_set:
        actions.append(_NextAction.INSPECT_DATABASE.value)
    if _WarnCode.RECOVERY_IN_PROGRESS.value in warning_set:
        actions.append(_NextAction.INSPECT_RECOVERY_RUN.value)
    if _WarnCode.MEMORY_RECONCILIATION_REPOSITORY_UNREACHABLE.value in warning_set:
        actions.append(_NextAction.INSPECT_MEMORY_RECONCILIATION_REPOSITORY.value)
    if _WarnCode.MEMORY_RECONCILIATION_TEMPORAL_BACKFILL_REQUIRED.value in warning_set:
        actions.append(_NextAction.PREVIEW_EXISTING_MEMORY_RECONCILIATION.value)
    if {
        _WarnCode.MEMORY_RECONCILIATION_REVIEW_REQUIRED.value,
        _WarnCode.MEMORY_RECONCILIATION_OPEN_CONFLICTS.value,
        _WarnCode.MEMORY_RECONCILIATION_REVIEWS_IN_PROGRESS.value,
    } & warning_set:
        actions.append(_NextAction.REVIEW_MEMORY_RECONCILIATION.value)
    if {
        _WarnCode.MEMORY_RECONCILIATION_PARTIAL_APPLY_PRESENT.value,
        _WarnCode.MEMORY_RECONCILIATION_FAILED_RESULTS_PRESENT.value,
    } & warning_set:
        actions.append(_NextAction.INSPECT_MEMORY_RECONCILIATION_FAILURES.value)
    if _WarnCode.MEMORY_RECONCILIATION_HARD_DELETE_DETECTED.value in warning_set:
        actions.append(_NextAction.AUDIT_MEMORY_RECONCILIATION_INTEGRITY.value)
    if warning_set & _RUNTIME_DRIFT_WARNINGS:
        actions.append(_NextAction.REBUILD_AND_REDEPLOY_RUNTIME.value)
    if warning_set & _RETRIEVAL_CANARY_WARNINGS:
        actions.append(_NextAction.INSPECT_RETRIEVAL_CANARY.value)
    if warning_set & _PROJECTION_INTEGRITY_WARNINGS:
        actions.append(_NextAction.REFRESH_PROJECTION_INTEGRITY.value)
    return actions


def _index_error_actions(
    index_errors: tuple[ObsidianIndexError, ...],
) -> list[str]:
    """Recommend operator actions for specific Obsidian index error codes.

    Args:
        index_errors: Persisted Obsidian index errors.

    Returns:
        Ordered list of recommended index-error remediation actions.
    """
    if not index_errors:
        return [_NextAction.INSPECT_OBSIDIAN_INDEX_ERRORS.value]
    codes = {error.error_code for error in index_errors}
    actions: list[str] = []
    if ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED in codes:
        actions.append(_NextAction.REVIEW_OBSIDIAN_FRONTMATTER_SECURITY_ERRORS.value)
    if codes & {
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
    }:
        actions.append(_NextAction.RESOLVE_DUPLICATE_CONTEXT_IDENTITY.value)
    if ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION in codes:
        actions.append(_NextAction.INSPECT_OBSIDIAN_PATH_SECURITY.value)
    if ObsidianIndexErrorCode.SOURCE_READ_FAILED in codes:
        actions.append(_NextAction.INSPECT_OBSIDIAN_SOURCE_STORAGE.value)
    if ObsidianIndexErrorCode.INDEX_WRITE_FAILED in codes:
        actions.append(_NextAction.INSPECT_OBSIDIAN_INDEX_STORAGE.value)
    repairable = codes - {
        ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
        ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION,
        ObsidianIndexErrorCode.SOURCE_READ_FAILED,
        ObsidianIndexErrorCode.INDEX_WRITE_FAILED,
    }
    if repairable:
        actions.append(_NextAction.PLAN_INDEX_ERROR_REPAIRS.value)
    return actions or [_NextAction.INSPECT_OBSIDIAN_INDEX_ERRORS.value]
