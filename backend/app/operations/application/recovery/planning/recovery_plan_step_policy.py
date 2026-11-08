"""Step planning, capability fencing, and plan hashing for recovery plans."""

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
    OperationalGraphProjectionStatus,
    OperationalReadinessWarningCode as _WarnCode,
)
from app.operations.domain.event_enum.recovery_step_enums import (
    RecoveryPlanBlockerCode,
    RecoveryStepCode,
)
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject

_MAX_PLANNED_NOTE_REPAIRS = 50
_REBUILD_GRAPH_STATUSES: frozenset[str] = frozenset(
    {
        OperationalGraphProjectionStatus.UNAVAILABLE.value,
        OperationalGraphProjectionStatus.UNINITIALIZED.value,
        OperationalGraphProjectionStatus.UNKNOWN.value,
    }
)
_RECONCILIATION_WARNINGS: frozenset[str] = frozenset(
    {
        _WarnCode.MEMORY_RECONCILIATION_REPOSITORY_UNREACHABLE.value,
        _WarnCode.MEMORY_RECONCILIATION_TEMPORAL_BACKFILL_REQUIRED.value,
        _WarnCode.MEMORY_RECONCILIATION_REVIEW_REQUIRED.value,
        _WarnCode.MEMORY_RECONCILIATION_OPEN_CONFLICTS.value,
        _WarnCode.MEMORY_RECONCILIATION_REVIEWS_IN_PROGRESS.value,
        _WarnCode.MEMORY_RECONCILIATION_PARTIAL_APPLY_PRESENT.value,
        _WarnCode.MEMORY_RECONCILIATION_FAILED_RESULTS_PRESENT.value,
        _WarnCode.MEMORY_RECONCILIATION_HARD_DELETE_DETECTED.value,
    }
)


def steps(
    readiness: OperationalReadinessSnapshot,
    error_note_paths: list[str] | None = None,
) -> list[RecoveryPlanStep]:
    """Assemble the ordered recovery steps required for the readiness state.

    Args:
        readiness: Current operational readiness snapshot.
        error_note_paths: Bounded index-error note paths for note-local repair.

    Returns:
        Ordered list of planned recovery steps.
    """
    if _reconciliation_only_issue(list(readiness.warnings)):
        return [
            RecoveryPlanStep(
                RecoveryStepCode.INSPECT_MEMORY_RECONCILIATION.value,
                "Inspect reconciliation diagnostics without rebuilding storage",
                False,
            ),
            RecoveryPlanStep(
                RecoveryStepCode.CURRENT_READINESS_CHECK.value,
                "Check current readiness after independent diagnostics",
                False,
            ),
        ]
    if not readiness.database.reachable:
        return [
            RecoveryPlanStep(
                RecoveryStepCode.INSPECT_POSTGRESQL_BACKUP_RESTORE.value,
                "Inspect PostgreSQL server backup and restore state",
                False,
            )
        ]
    warning_set = set(readiness.warnings)
    planned_steps = [
        RecoveryPlanStep(
            RecoveryStepCode.SNAPSHOT_SOURCES.value,
            "Snapshot source vault metadata",
            False,
        )
    ]
    if error_note_paths:
        planned_steps.append(
            RecoveryPlanStep(
                RecoveryStepCode.REPAIR_MANAGED_FRONTMATTER.value,
                "Re-parse and revalidate index-error notes in place",
                True,
            )
        )
    if {
        _WarnCode.OBSIDIAN_STALE_NOTES_PRESENT.value,
        _WarnCode.RAG_FTS_NOT_HEALTHY.value,
    } & warning_set:
        planned_steps.append(
            RecoveryPlanStep(
                RecoveryStepCode.VAULT_REINDEX.value,
                "Rebuild Obsidian and lexical indexes",
                True,
            )
        )
    if {
        _WarnCode.RAG_VECTOR_NOT_HEALTHY.value,
        _WarnCode.RAG_EMBEDDING_REINDEX_REQUIRED.value,
        _WarnCode.RAG_EMBEDDING_NOT_HEALTHY.value,
        _WarnCode.RAG_DEFAULT_STRATEGY_NOT_HYBRID.value,
        _WarnCode.RAG_STATUS_WARNINGS_PRESENT.value,
    } & warning_set:
        planned_steps.append(
            RecoveryPlanStep(
                RecoveryStepCode.EMBEDDING_REINDEX.value,
                "Rebuild retrieval embeddings",
                True,
            )
        )
    needs_graph_rebuild = readiness.graph.status in _REBUILD_GRAPH_STATUSES or any(
        step.code == RecoveryStepCode.VAULT_REINDEX.value for step in planned_steps
    )
    if needs_graph_rebuild:
        planned_steps.append(
            RecoveryPlanStep(
                RecoveryStepCode.GRAPH_REVALIDATE.value,
                "Revalidate the PostgreSQL graph projection",
                True,
            )
        )
    if readiness.graph.last_run_issue_total > 0 or needs_graph_rebuild:
        planned_steps.append(
            RecoveryPlanStep(
                RecoveryStepCode.LINK_REVALIDATE.value,
                "Inspect bounded graph link diagnostics",
                False,
            )
        )
    if {
        _WarnCode.MAINTENANCE_DLQ_PRESENT.value,
        _WarnCode.MAINTENANCE_DLQ_UNKNOWN_OUTCOME.value,
    } & warning_set:
        planned_steps.append(
            RecoveryPlanStep(
                RecoveryStepCode.DLQ_RECONCILE.value,
                "Reconcile maintenance dead-letter effects without retry",
                False,
            )
        )
    planned_steps.append(
        RecoveryPlanStep(
            RecoveryStepCode.CURRENT_READINESS_CHECK.value,
            "Verify current operational readiness",
            False,
        )
    )
    return planned_steps


def plan_hash(
    planned_steps: list[RecoveryPlanStep],
    diagnosis: list[str],
    source_snapshot: RecoverySourceSnapshot,
) -> str:
    """Hash one plan's bounded semantic content and source revision.

    The hash covers the planned step order, the diagnosis, and the full
    source manifest, so any source drift between dry-run and apply changes
    the hash and fails the apply fence.

    Args:
        planned_steps: Planned steps in execution order.
        diagnosis: Bounded diagnosis codes.
        source_snapshot: Source manifest snapshot.

    Returns:
        Deterministic SHA-256 plan hash.
    """
    manifest: JSONObject = {}
    for note_path, token in sorted(source_snapshot.markdown_manifest.items()):
        manifest[note_path] = token
    payload: JSONObject = {
        "steps": [step.code for step in planned_steps],
        "diagnosis": sorted(diagnosis),
        "manifest": manifest,
    }
    return sha256(
        dumps_pretty_json(payload),
    ).hexdigest()


def missing_step_capabilities(
    planned_steps: list[RecoveryPlanStep],
    *,
    embedding_recovery_available: bool,
    graph_rebuild_available: bool,
    link_diagnostics_available: bool,
    dlq_reconcile_available: bool,
    current_compact_reader_available: bool,
) -> list[str]:
    """Return explicit blockers for cause-specific steps without an owner.

    Args:
        planned_steps: Planned recovery steps.
        embedding_recovery_available: Whether configured bounded embedding recovery exists.
        graph_rebuild_available: Whether the existing graph rebuild owner is wired.
        link_diagnostics_available: Whether bounded link diagnostics are wired.
        dlq_reconcile_available: Whether the read-only DLQ reconciler is wired.
        current_compact_reader_available: Whether the CURRENT compact reader is wired.

    Returns:
        Stable prerequisite blocker codes.
    """
    codes = {step.code for step in planned_steps}
    blockers: list[str] = []
    if (
        RecoveryStepCode.EMBEDDING_REINDEX.value in codes
        and not embedding_recovery_available
    ):
        blockers.append(RecoveryPlanBlockerCode.EMBEDDING_RECOVERY_UNAVAILABLE.value)
    if RecoveryStepCode.GRAPH_REVALIDATE.value in codes and not graph_rebuild_available:
        blockers.append(RecoveryPlanBlockerCode.GRAPH_REBUILD_UNAVAILABLE.value)
    if (
        RecoveryStepCode.LINK_REVALIDATE.value in codes
        and not link_diagnostics_available
    ):
        blockers.append(RecoveryPlanBlockerCode.LINK_DIAGNOSTICS_UNAVAILABLE.value)
    if RecoveryStepCode.DLQ_RECONCILE.value in codes and not dlq_reconcile_available:
        blockers.append(RecoveryPlanBlockerCode.DLQ_RECONCILE_UNAVAILABLE.value)
    if (
        RecoveryStepCode.CURRENT_READINESS_CHECK.value in codes
        and not current_compact_reader_available
    ):
        blockers.append(
            RecoveryPlanBlockerCode.CURRENT_COMPACT_READER_UNAVAILABLE.value
        )
    return blockers


def bounded_error_note_paths(
    index_errors: list[str],
) -> list[str]:
    """Bound the planned note-local repair list.

    Args:
        index_errors: Index-error note paths from the vault status scan.

    Returns:
        Bounded, de-duplicated note paths in stable order.
    """
    return list(dict.fromkeys(index_errors))[:_MAX_PLANNED_NOTE_REPAIRS]


def _reconciliation_only_issue(warnings: list[str]) -> bool:
    """Return whether readiness contains only reconciliation-domain warnings.

    Args:
        warnings: Collected readiness warning codes.

    Returns:
        True when warnings are non-empty and all belong to memory reconciliation.
    """
    return bool(warnings) and all(
        warning in _RECONCILIATION_WARNINGS
        or warning.startswith("memory_reconciliation_")
        for warning in warnings
    )
