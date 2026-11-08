"""Retry and blocked-run policies for operational recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.operations.application.recovery.execution.recovery_run_manifest import (
    RecoveryManifestStore,
    manifest_path_by_id,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlan,
)
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
    RecoveryRunStepResult,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
    RecoveryStepStatus,
)
from app.operations.domain.event_enum.recovery_step_enums import (
    RecoveryStepErrorCode,
)


def parent_run_for_retry(parent_run_id: str | None) -> RecoveryRun | None:
    """Load the persisted parent recovery run when a retry parent id is supplied.

    Args:
        parent_run_id: Identifier of the parent recovery run, or None.

    Returns:
        Loaded parent RecoveryRun, or None when absent.
    """
    if parent_run_id is None:
        return None
    manifest_path = manifest_path_by_id(run_id=parent_run_id)
    if not manifest_path.exists():
        return None
    return RecoveryManifestStore.read(manifest_path)


def successful_parent_steps(
    parent_run: RecoveryRun | None,
) -> dict[tuple[str, str], RecoveryRunStepResult]:
    """Index succeeded parent-run steps by step code and input hash.

    Args:
        parent_run: Loaded parent recovery run, or None.

    Returns:
        Mapping from (step_code, input_hash) to the succeeded parent step result.
    """
    if parent_run is None:
        return {}
    return {
        (step.code, step.input_hash): step
        for step in parent_run.step_results
        if step.status is RecoveryStepStatus.SUCCEEDED and step.input_hash
    }


def blocked_run(plan: RecoveryPlan, manifest_path: Path) -> RecoveryRun:
    """Construct a BLOCKED recovery run record when preflight blocks execution.

    Args:
        plan: Recovery plan that cannot execute automatically.
        manifest_path: Filesystem path where the blocked manifest will be saved.

    Returns:
        BLOCKED RecoveryRun instance summarizing the plan blockers.
    """
    now = datetime.now(UTC)
    return RecoveryRun(
        id=plan.id,
        parent_run_id=plan.parent_run_id,
        idempotency_key=plan.idempotency_key,
        admitted_plan_hash=plan.plan_hash,
        trigger=plan.trigger,
        actor=plan.actor,
        status=RecoveryRunStatus.BLOCKED,
        current_step=None,
        started_at=now,
        updated_at=now,
        finished_at=now,
        source_snapshot=plan.source_snapshot,
        diagnosis=plan.diagnosis,
        planned_steps=plan.steps,
        step_results=(),
        rebuild_results={},
        verification_results={},
        error_code=RecoveryStepErrorCode.RECOVERY_PLAN_BLOCKED.value,
        error_summary=", ".join(plan.blocked_reasons),
        next_actions=plan.next_actions,
        manifest_path=str(manifest_path),
    )


def default_retry_idempotency_key(parent_run_id: str) -> str:
    """Derive the default idempotency key for retrying a parent recovery run.

    Args:
        parent_run_id: Identifier of the parent recovery run being retried.

    Returns:
        Deterministic retry idempotency key string.
    """
    return f"retry:{parent_run_id}"
