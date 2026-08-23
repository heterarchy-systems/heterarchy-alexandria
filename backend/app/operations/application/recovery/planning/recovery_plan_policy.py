"""Blocker, status, step, diagnosis, and next-action policy for recovery plans."""

from __future__ import annotations

from hashlib import sha256

from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlanStep,
    RecoverySourceSnapshot,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)


def _default_idempotency_key(
    trigger: str,
    actor: str,
) -> str:
    """Execute default idempotency key.

    Args:
        trigger: Trigger used by this operation.
        actor: Actor used by this operation.

    Returns:
        str result produced by default idempotency key.
    """
    seed = f"postgresql:{trigger}:{actor}"
    return sha256(seed.encode("utf-8")).hexdigest()[:24]


def _blocked_reasons(
    readiness: OperationalReadinessSnapshot,
    source_snapshot: RecoverySourceSnapshot,
) -> list[str]:
    """Execute blocked reasons.

    Args:
        readiness: Readiness used by this operation.
        source_snapshot: Source snapshot used by this operation.

    Returns:
        list[str] result produced by blocked reasons.
    """
    reasons: list[str] = []
    if not readiness.database.reachable:
        reasons.append("postgresql_server_recovery_required")
    if source_snapshot.access_error is not None:
        reasons.append(source_snapshot.access_error)
    if not readiness.vault.exists:
        reasons.append("vault_not_found")
    if not readiness.vault.alexandria_root_exists:
        reasons.append("alexandria_root_not_found")
    if source_snapshot.managed_markdown_count == 0:
        reasons.append("managed_markdown_not_found")
    return reasons


def _plan_status(
    readiness: OperationalReadinessSnapshot,
    blocked_reasons: list[str],
) -> OperationalReadinessStatus:
    """Execute plan status.

    Args:
        readiness: Readiness used by this operation.
        blocked_reasons: Blocked reasons used by this operation.

    Returns:
        OperationalReadinessStatus result produced by plan status.
    """
    if blocked_reasons:
        return OperationalReadinessStatus.BLOCKED
    if readiness.status is OperationalReadinessStatus.RECOVERY_REQUIRED:
        return OperationalReadinessStatus.RECOVERY_REQUIRED
    return readiness.status


def _diagnosis(
    readiness: OperationalReadinessSnapshot,
) -> list[str]:
    """Execute diagnosis.

    Args:
        readiness: Readiness used by this operation.

    Returns:
        list[str] result produced by diagnosis.
    """
    if not readiness.database.reachable:
        return ["POSTGRESQL_DATABASE_UNREACHABLE"]
    return list(readiness.warnings)


def _steps(
    readiness: OperationalReadinessSnapshot,
) -> list[RecoveryPlanStep]:
    """Execute steps.

    Args:
        readiness: Readiness used by this operation.

    Returns:
        list[RecoveryPlanStep] result produced by steps.
    """
    if _reconciliation_only_issue(list(readiness.warnings)):
        return [
            RecoveryPlanStep(
                "inspect_memory_reconciliation",
                "Inspect reconciliation diagnostics without rebuilding storage",
                False,
            )
        ]
    if not readiness.database.reachable:
        return [
            RecoveryPlanStep(
                "inspect_postgresql_backup_restore",
                "Inspect PostgreSQL server backup and restore state",
                False,
            )
        ]
    warning_set = set(readiness.warnings)
    steps = [
        RecoveryPlanStep("snapshot_sources", "Snapshot source vault metadata", False)
    ]
    if {
        "obsidian_stale_notes_present",
        "obsidian_error_notes_present",
        "rag_fts_not_healthy",
    } & warning_set:
        steps.append(
            RecoveryPlanStep(
                "reindex_vault", "Rebuild Obsidian and lexical indexes", True
            )
        )
    if {
        "rag_vector_not_healthy",
        "rag_embedding_reindex_required",
        "rag_embedding_not_healthy",
        "rag_default_strategy_not_hybrid",
        "rag_status_warnings_present",
    } & warning_set:
        steps.append(
            RecoveryPlanStep("reindex_embeddings", "Rebuild retrieval embeddings", True)
        )
    if len(steps) > 1:
        steps.append(
            RecoveryPlanStep("verify_readiness", "Verify operational readiness", False)
        )
    return steps


def _next_actions(
    status: OperationalReadinessStatus,
    blocked_reasons: list[str],
    warnings: list[str],
) -> list[str]:
    """Execute next actions.

    Args:
        status: Status value used by this operation.
        blocked_reasons: Blocked reasons used by this operation.
        warnings: Warnings used by this operation.

    Returns:
        list[str] result produced by next actions.
    """
    if blocked_reasons:
        if "postgresql_server_recovery_required" in blocked_reasons:
            return ["restore_postgresql_from_backup"]
        if {
            "vault_not_found",
            "alexandria_root_not_found",
            "managed_markdown_not_found",
            "source_snapshot_unreadable",
        } & set(blocked_reasons):
            return ["inspect_vault_configuration"]
        return ["resolve_recovery_blockers"]
    warning_set = set(warnings)
    if {"database_unreachable", "database_integrity_not_healthy"} & warning_set:
        return ["inspect_database"]
    if {
        "vault_not_found",
        "alexandria_root_not_found",
        "obsidian_stale_notes_present",
        "obsidian_error_notes_present",
    } & warning_set:
        return ["inspect_vault_configuration"]
    reconciliation_actions: list[str] = []
    if "memory_reconciliation_repository_unreachable" in warning_set:
        reconciliation_actions.append("inspect_memory_reconciliation_repository")
    if {
        "memory_reconciliation_partial_apply_present",
        "memory_reconciliation_failed_results_present",
    } & warning_set:
        reconciliation_actions.append("inspect_memory_reconciliation_failures")
    if "memory_reconciliation_hard_delete_detected" in warning_set:
        reconciliation_actions.append("audit_memory_reconciliation_integrity")
    if "memory_reconciliation_temporal_backfill_required" in warning_set:
        reconciliation_actions.append("preview_existing_memory_reconciliation")
    if {
        "memory_reconciliation_review_required",
        "memory_reconciliation_open_conflicts",
        "memory_reconciliation_reviews_in_progress",
    } & warning_set:
        reconciliation_actions.append("review_memory_reconciliation")
    if reconciliation_actions:
        return list(dict.fromkeys(reconciliation_actions))
    if status is OperationalReadinessStatus.RECOVERY_REQUIRED:
        return ["start_recovery_run"]
    return ["no_recovery_required"]


def _reconciliation_only_issue(warnings: list[str]) -> bool:
    """Return whether readiness contains only reconciliation-domain warnings.

    Args:
        warnings: Warnings used by this operation.

    Returns:
        Whether reconciliation only issue.
    """
    return bool(warnings) and all(
        warning.startswith("memory_reconciliation_") for warning in warnings
    )
