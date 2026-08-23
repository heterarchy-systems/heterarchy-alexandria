"""Retry, interruption, and blocked-run policies for operational recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.operations.application.recovery.execution.recovery_run_manifest import (
    RecoveryActiveLockPayload,
    _manifest_path_by_id,
    _run_from_manifest,
)
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlan,
    RecoveryPlanStep,
    RecoverySourceSnapshot,
)
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
    RecoveryRunStepResult,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
    RecoveryStepStatus,
)


def _parent_run_for_retry(parent_run_id: str | None) -> RecoveryRun | None:
    """Execute parent run for retry.

    Args:
        parent_run_id: Identifier for parent run.

    Returns:
        RecoveryRun | None result produced by parent run for retry.
    """
    if parent_run_id is None:
        return None
    manifest_path = _manifest_path_by_id(run_id=parent_run_id)
    if not manifest_path.exists():
        return None
    return _run_from_manifest(manifest_path)


def _successful_parent_steps(
    parent_run: RecoveryRun | None,
) -> dict[tuple[str, str], RecoveryRunStepResult]:
    """Execute successful parent steps.

    Args:
        parent_run: Parent run used by this operation.

    Returns:
        dict[tuple[str, str], RecoveryRunStepResult] result produced by successful parent steps.
    """
    if parent_run is None:
        return {}
    return {
        (step.code, step.input_hash): step
        for step in parent_run.step_results
        if step.status is RecoveryStepStatus.SUCCEEDED and step.input_hash
    }


def _recovery_steps() -> list[RecoveryPlanStep]:
    """Execute recovery steps.

    Returns:
        list[RecoveryPlanStep] result produced by recovery steps.
    """
    return [
        RecoveryPlanStep("snapshot_sources", "Snapshot source vault metadata", False),
        RecoveryPlanStep("reindex_vault", "Rebuild Obsidian index cache", True),
        RecoveryPlanStep("reindex_embeddings", "Rebuild retrieval embeddings", True),
        RecoveryPlanStep("verify_readiness", "Verify operational readiness", False),
    ]


def _blocked_run(plan: RecoveryPlan, manifest_path: Path) -> RecoveryRun:
    """Execute blocked run.

    Args:
        plan: Plan used by this operation.
        manifest_path: Manifest path used by this operation.

    Returns:
        RecoveryRun result produced by blocked run.
    """
    now = datetime.now(UTC)
    return RecoveryRun(
        id=plan.id,
        parent_run_id=plan.parent_run_id,
        idempotency_key=plan.idempotency_key,
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
        error_code="RECOVERY_PLAN_BLOCKED",
        error_summary=", ".join(plan.blocked_reasons),
        next_actions=plan.next_actions,
        manifest_path=str(manifest_path),
    )


def _interrupted_active_run(
    active_lock: RecoveryActiveLockPayload,
    source_snapshot: RecoverySourceSnapshot,
    manifest_path: Path,
) -> RecoveryRun:
    """Execute interrupted active run.

    Args:
        active_lock: Active lock used by this operation.
        source_snapshot: Source snapshot used by this operation.
        manifest_path: Manifest path used by this operation.

    Returns:
        RecoveryRun result produced by interrupted active run.
    """
    started_at = active_lock.started_at or datetime.now(UTC)
    now = datetime.now(UTC)
    return RecoveryRun(
        id=active_lock.run_id,
        parent_run_id=None,
        idempotency_key=active_lock.idempotency_key or "",
        trigger=active_lock.trigger,
        actor=active_lock.actor,
        status=RecoveryRunStatus.BLOCKED,
        current_step=active_lock.current_step,
        started_at=started_at,
        updated_at=now,
        finished_at=now,
        source_snapshot=source_snapshot,
        diagnosis=("RECOVERY_INTERRUPTED_AFTER_RESTART",),
        planned_steps=tuple(_recovery_steps()),
        step_results=(),
        rebuild_results={},
        verification_results={},
        error_code="RECOVERY_INTERRUPTED_AFTER_RESTART",
        error_summary=(
            "Recovery active lock existed without a completed manifest; "
            "the run was blocked for operator retry after restart."
        ),
        next_actions=("retry_recovery_run", "inspect_recovery_run"),
        manifest_path=str(manifest_path),
    )


def _default_retry_idempotency_key(parent_run_id: str) -> str:
    """Execute default retry idempotency key.

    Args:
        parent_run_id: Identifier for parent run.

    Returns:
        str result produced by default retry idempotency key.
    """
    return f"retry:{parent_run_id}"
