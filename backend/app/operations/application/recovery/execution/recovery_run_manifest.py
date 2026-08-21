"""Typed persistence boundary for recovery active locks and run manifests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from app.operations.application.recovery.planning.operational_recovery_paths import (
    recovery_directory as _recovery_dir,
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
from app.operations.domain.recovery_state_constants import (
    UNREADABLE_ACTIVE_RECOVERY_RUN_ID,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_dict_default,
)
from app.shared.serialization.model_codec import schema_payload
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject
from pydantic import ConfigDict, ValidationError


class RecoveryPersistencePayload(StrictSchemaModel):
    """Base validation contract for persisted recovery JSON."""

    model_config = ConfigDict(extra="ignore", frozen=True, validate_default=True)


class RecoveryActiveLockPayload(RecoveryPersistencePayload):
    """Validated active recovery lock persisted in application recovery state."""

    run_id: str
    idempotency_key: str | None = None
    trigger: str = "manual"
    actor: str = "operator"
    started_at: datetime | None = None
    current_step: str | None = None
    updated_at: datetime | None = None
    read_error: str | None = None


class RecoverySourceSnapshotPayload(RecoveryPersistencePayload):
    """Persisted source-preservation evidence."""

    vault_path: str
    alexandria_root: str
    managed_markdown_count: int
    representative_path: str | None = None
    representative_sha256: str | None = None
    disk_free_bytes: int | None = None
    access_error: str | None = None
    markdown_manifest: Annotated[
        dict[str, str],
        described_field("Markdown manifest for this recovery source snapshot payload."),
    ] = schema_dict_default()


class RecoveryPlanStepPayload(RecoveryPersistencePayload):
    """Persisted recovery plan step."""

    code: str
    title: str
    mutates_state: bool


class RecoveryStepResultPayload(RecoveryPersistencePayload):
    """Persisted recovery execution step result."""

    code: str
    status: RecoveryStepStatus
    attempts: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_hash: str = ""
    result: Annotated[
        JSONObject, described_field("Result for this recovery step result payload.")
    ] = schema_dict_default()


class RecoveryRunManifestPayload(RecoveryPersistencePayload):
    """Validated complete recovery run manifest."""

    id: str
    parent_run_id: str | None = None
    idempotency_key: str
    trigger: str
    actor: str
    status: RecoveryRunStatus
    current_step: str | None = None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    source_snapshot: RecoverySourceSnapshotPayload
    diagnosis: Annotated[
        tuple[str, ...],
        described_field("Diagnosis for this recovery run manifest payload."),
    ] = ()
    planned_steps: Annotated[
        tuple[RecoveryPlanStepPayload, ...],
        described_field("Planned steps for this recovery run manifest payload."),
    ] = ()
    step_results: Annotated[
        tuple[RecoveryStepResultPayload, ...],
        described_field("Step results for this recovery run manifest payload."),
    ] = ()
    rebuild_results: Annotated[
        JSONObject,
        described_field("Rebuild results for this recovery run manifest payload."),
    ] = schema_dict_default()
    verification_results: Annotated[
        JSONObject,
        described_field("Verification results for this recovery run manifest payload."),
    ] = schema_dict_default()
    error_code: str | None = None
    error_summary: str | None = None
    next_actions: Annotated[
        tuple[str, ...],
        described_field("Next actions for this recovery run manifest payload."),
    ] = ()


def _manifest_path(plan: RecoveryPlan) -> Path:
    return _manifest_path_by_id(run_id=plan.id)


def _manifest_path_by_id(run_id: str) -> Path:
    return _recovery_dir() / run_id / "recovery-run.json"


def _active_lock_path() -> Path:
    return _recovery_dir() / "active-run.json"


def _read_active_lock() -> RecoveryActiveLockPayload | None:
    path = _active_lock_path()
    if not path.exists():
        return None
    try:
        return RecoveryActiveLockPayload.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        return _unreadable_active_lock()


def _unreadable_active_lock() -> RecoveryActiveLockPayload:
    return RecoveryActiveLockPayload(
        run_id=UNREADABLE_ACTIVE_RECOVERY_RUN_ID,
        read_error="active_recovery_lock_unreadable",
    )


def _write_active_lock(plan: RecoveryPlan) -> None:
    path = _active_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = RecoveryActiveLockPayload(
        run_id=plan.id,
        idempotency_key=plan.idempotency_key,
        trigger=plan.trigger,
        actor=plan.actor,
        started_at=datetime.now(UTC),
    )
    path.write_bytes(dumps_pretty_json(schema_payload(payload)))


def _checkpoint_active_step(plan: RecoveryPlan, current_step: str) -> str:
    path = _active_lock_path()
    payload = _read_active_lock()
    if payload is None or payload.run_id != plan.id:
        payload = RecoveryActiveLockPayload(
            run_id=plan.id,
            idempotency_key=plan.idempotency_key,
            trigger=plan.trigger,
            actor=plan.actor,
            started_at=datetime.now(UTC),
        )
    payload = payload.model_copy(
        update={"current_step": current_step, "updated_at": datetime.now(UTC)}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dumps_pretty_json(schema_payload(payload)))
    return current_step


def _clear_active_lock(plan: RecoveryPlan) -> None:
    path = _active_lock_path()
    if not path.exists():
        return
    payload = _read_active_lock()
    if payload is not None and payload.run_id != plan.id:
        return
    path.unlink()


def _clear_active_lock_for_run_id(run_id: str) -> None:
    path = _active_lock_path()
    if not path.exists():
        return
    payload = _read_active_lock()
    if payload is None or payload.run_id != run_id:
        return
    path.unlink()


def _write_manifest(run: RecoveryRun) -> None:
    path = Path(run.manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dumps_pretty_json(schema_payload(_run_payload(run))))


def _run_from_manifest(path: Path) -> RecoveryRun:
    payload = RecoveryRunManifestPayload.model_validate_json(path.read_bytes())
    return _run_from_payload(payload, str(path))


def _run_payload(run: RecoveryRun) -> RecoveryRunManifestPayload:
    return RecoveryRunManifestPayload(
        id=run.id,
        parent_run_id=run.parent_run_id,
        idempotency_key=run.idempotency_key,
        trigger=run.trigger,
        actor=run.actor,
        status=run.status,
        current_step=run.current_step,
        started_at=run.started_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
        source_snapshot=_source_snapshot_payload(run.source_snapshot),
        diagnosis=tuple(run.diagnosis),
        planned_steps=tuple(_planned_step_payload(step) for step in run.planned_steps),
        step_results=tuple(_step_result_payload(step) for step in run.step_results),
        rebuild_results=run.rebuild_results,
        verification_results=run.verification_results,
        error_code=run.error_code,
        error_summary=run.error_summary,
        next_actions=tuple(run.next_actions),
    )


def _source_snapshot_payload(
    snapshot: RecoverySourceSnapshot,
) -> RecoverySourceSnapshotPayload:
    return RecoverySourceSnapshotPayload(
        vault_path=snapshot.vault_path,
        alexandria_root=snapshot.alexandria_root,
        managed_markdown_count=snapshot.managed_markdown_count,
        representative_path=snapshot.representative_path,
        representative_sha256=snapshot.representative_sha256,
        disk_free_bytes=snapshot.disk_free_bytes,
        access_error=snapshot.access_error,
        markdown_manifest=dict(snapshot.markdown_manifest),
    )


def _planned_step_payload(step: RecoveryPlanStep) -> RecoveryPlanStepPayload:
    return RecoveryPlanStepPayload(
        code=step.code,
        title=step.title,
        mutates_state=step.mutates_state,
    )


def _step_result_payload(step: RecoveryRunStepResult) -> RecoveryStepResultPayload:
    return RecoveryStepResultPayload(
        code=step.code,
        status=step.status,
        attempts=step.attempts,
        started_at=step.started_at,
        finished_at=step.finished_at,
        input_hash=step.input_hash,
        result=step.result,
    )


def _run_from_payload(
    payload: RecoveryRunManifestPayload,
    manifest_path: str,
) -> RecoveryRun:
    return RecoveryRun(
        id=payload.id,
        parent_run_id=payload.parent_run_id,
        idempotency_key=payload.idempotency_key,
        trigger=payload.trigger,
        actor=payload.actor,
        status=payload.status,
        current_step=payload.current_step,
        started_at=payload.started_at,
        updated_at=payload.updated_at,
        finished_at=payload.finished_at,
        source_snapshot=_source_snapshot_from_payload(payload.source_snapshot),
        diagnosis=tuple(payload.diagnosis),
        planned_steps=tuple(
            _planned_step_from_payload(item) for item in payload.planned_steps
        ),
        step_results=tuple(
            _step_result_from_payload(item) for item in payload.step_results
        ),
        rebuild_results=payload.rebuild_results,
        verification_results=payload.verification_results,
        error_code=payload.error_code,
        error_summary=payload.error_summary,
        next_actions=tuple(payload.next_actions),
        manifest_path=manifest_path,
    )


def _source_snapshot_from_payload(
    payload: RecoverySourceSnapshotPayload,
) -> RecoverySourceSnapshot:
    return RecoverySourceSnapshot(
        vault_path=payload.vault_path,
        alexandria_root=payload.alexandria_root,
        managed_markdown_count=payload.managed_markdown_count,
        representative_path=payload.representative_path,
        representative_sha256=payload.representative_sha256,
        disk_free_bytes=payload.disk_free_bytes,
        access_error=payload.access_error,
        markdown_manifest=dict(payload.markdown_manifest),
    )


def _planned_step_from_payload(payload: RecoveryPlanStepPayload) -> RecoveryPlanStep:
    return RecoveryPlanStep(
        code=payload.code,
        title=payload.title,
        mutates_state=payload.mutates_state,
    )


def _step_result_from_payload(
    payload: RecoveryStepResultPayload,
) -> RecoveryRunStepResult:
    return RecoveryRunStepResult(
        code=payload.code,
        status=payload.status,
        attempts=payload.attempts,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
        input_hash=payload.input_hash,
        result=payload.result,
    )
