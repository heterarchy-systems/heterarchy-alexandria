"""Blocker, status, diagnosis, and next-action policy for recovery plans."""

from __future__ import annotations

from hashlib import sha256

from app.operations.application.recovery.planning.recovery_plan_step_policy import (
    bounded_error_note_paths,
    missing_step_capabilities,
    plan_hash,
    steps,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.entities.recovery_plan import RecoverySourceSnapshot
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessNextAction as _NextAction,
    OperationalReadinessStatus,
    OperationalReadinessWarningCode as _WarnCode,
)
from app.operations.domain.event_enum.recovery_step_enums import (
    RecoveryDiagnosisSummaryCode,
    RecoveryPlanBlockerCode,
)

__all__ = (
    "blocked_reasons",
    "bounded_error_note_paths",
    "default_idempotency_key",
    "diagnosis",
    "missing_step_capabilities",
    "next_actions",
    "plan_hash",
    "plan_status",
    "steps",
)


def default_idempotency_key(
    trigger: str,
    actor: str,
) -> str:
    """Derive a deterministic idempotency key from the trigger and actor.

    Args:
        trigger: Recovery trigger identifier.
        actor: Actor requesting the recovery plan.

    Returns:
        Truncated 24-character hex SHA-256 digest.
    """
    seed = f"postgresql:{trigger}:{actor}"
    return sha256(seed.encode("utf-8")).hexdigest()[:24]


def blocked_reasons(
    readiness: OperationalReadinessSnapshot,
    source_snapshot: RecoverySourceSnapshot,
) -> list[str]:
    """Collect prerequisite blockers that prevent automatic recovery execution.

    Args:
        readiness: Current operational readiness snapshot.
        source_snapshot: Captured vault source snapshot.

    Returns:
        Ordered list of blocker reason codes.
    """
    reasons: list[str] = []
    if not readiness.database.reachable:
        reasons.append(
            RecoveryPlanBlockerCode.POSTGRESQL_SERVER_RECOVERY_REQUIRED.value
        )
    if source_snapshot.access_error is not None:
        reasons.append(source_snapshot.access_error)
    if not readiness.vault.exists:
        reasons.append(_WarnCode.VAULT_NOT_FOUND.value)
    if not readiness.vault.alexandria_root_exists:
        reasons.append(_WarnCode.ALEXANDRIA_ROOT_NOT_FOUND.value)
    if source_snapshot.managed_markdown_count == 0:
        reasons.append(RecoveryPlanBlockerCode.MANAGED_MARKDOWN_NOT_FOUND.value)
    return reasons


def plan_status(
    readiness: OperationalReadinessSnapshot,
    plan_blocked_reasons: list[str],
) -> OperationalReadinessStatus:
    """Classify the recovery plan status from readiness and blocker evidence.

    Args:
        readiness: Current operational readiness snapshot.
        plan_blocked_reasons: Collected recovery plan blocker reasons.

    Returns:
        Classified operational readiness status for the recovery plan.
    """
    if plan_blocked_reasons:
        return OperationalReadinessStatus.BLOCKED
    if readiness.status is OperationalReadinessStatus.RECOVERY_REQUIRED:
        return OperationalReadinessStatus.RECOVERY_REQUIRED
    return readiness.status


def diagnosis(
    readiness: OperationalReadinessSnapshot,
) -> list[str]:
    """Derive bounded diagnostic codes explaining the recovery need.

    Args:
        readiness: Current operational readiness snapshot.

    Returns:
        Ordered list of diagnosis codes.
    """
    if not readiness.database.reachable:
        return [RecoveryDiagnosisSummaryCode.POSTGRESQL_DATABASE_UNREACHABLE.value]
    return list(readiness.warnings)


def next_actions(
    status: OperationalReadinessStatus,
    plan_blocked_reasons: list[str],
    warnings: list[str],
) -> list[str]:
    """Recommend next operator actions for a recovery dry-run plan.

    Args:
        status: Classified recovery plan status.
        plan_blocked_reasons: Collected recovery plan blocker reasons.
        warnings: Collected readiness warning codes.

    Returns:
        Ordered list of recommended operator action codes.
    """
    if plan_blocked_reasons:
        if (
            RecoveryPlanBlockerCode.POSTGRESQL_SERVER_RECOVERY_REQUIRED.value
            in plan_blocked_reasons
        ):
            return [_NextAction.RESTORE_POSTGRESQL_FROM_BACKUP.value]
        if {
            _WarnCode.VAULT_NOT_FOUND.value,
            _WarnCode.ALEXANDRIA_ROOT_NOT_FOUND.value,
            RecoveryPlanBlockerCode.MANAGED_MARKDOWN_NOT_FOUND.value,
            RecoveryPlanBlockerCode.SOURCE_SNAPSHOT_UNREADABLE.value,
        } & set(plan_blocked_reasons):
            return [_NextAction.INSPECT_VAULT_CONFIGURATION.value]
        return [_NextAction.RESOLVE_RECOVERY_BLOCKERS.value]
    warning_set = set(warnings)
    if {
        _WarnCode.DATABASE_UNREACHABLE.value,
        _WarnCode.DATABASE_INTEGRITY_NOT_HEALTHY.value,
    } & warning_set:
        return [_NextAction.INSPECT_DATABASE.value]
    if {
        _WarnCode.VAULT_NOT_FOUND.value,
        _WarnCode.ALEXANDRIA_ROOT_NOT_FOUND.value,
    } & warning_set:
        return [_NextAction.INSPECT_VAULT_CONFIGURATION.value]
    reconciliation_actions: list[str] = []
    if _WarnCode.MEMORY_RECONCILIATION_REPOSITORY_UNREACHABLE.value in warning_set:
        reconciliation_actions.append(
            _NextAction.INSPECT_MEMORY_RECONCILIATION_REPOSITORY.value
        )
    if {
        _WarnCode.MEMORY_RECONCILIATION_PARTIAL_APPLY_PRESENT.value,
        _WarnCode.MEMORY_RECONCILIATION_FAILED_RESULTS_PRESENT.value,
    } & warning_set:
        reconciliation_actions.append(
            _NextAction.INSPECT_MEMORY_RECONCILIATION_FAILURES.value
        )
    if _WarnCode.MEMORY_RECONCILIATION_HARD_DELETE_DETECTED.value in warning_set:
        reconciliation_actions.append(
            _NextAction.AUDIT_MEMORY_RECONCILIATION_INTEGRITY.value
        )
    if _WarnCode.MEMORY_RECONCILIATION_TEMPORAL_BACKFILL_REQUIRED.value in warning_set:
        reconciliation_actions.append(
            _NextAction.PREVIEW_EXISTING_MEMORY_RECONCILIATION.value
        )
    if {
        _WarnCode.MEMORY_RECONCILIATION_REVIEW_REQUIRED.value,
        _WarnCode.MEMORY_RECONCILIATION_OPEN_CONFLICTS.value,
        _WarnCode.MEMORY_RECONCILIATION_REVIEWS_IN_PROGRESS.value,
    } & warning_set:
        reconciliation_actions.append(_NextAction.REVIEW_MEMORY_RECONCILIATION.value)
    if reconciliation_actions:
        return list(dict.fromkeys(reconciliation_actions))
    if status is OperationalReadinessStatus.RECOVERY_REQUIRED:
        return [_NextAction.START_RECOVERY_RUN.value]
    return [_NextAction.NO_RECOVERY_REQUIRED.value]
