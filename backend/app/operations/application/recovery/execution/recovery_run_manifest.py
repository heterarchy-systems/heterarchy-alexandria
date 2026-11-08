"""Typed persistence boundary for recovery active locks and run manifests."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from fcntl import LOCK_EX, flock
from pathlib import Path
from typing import Annotated

from pydantic import ConfigDict, Field, ValidationError

from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
    RecoveryRunObservationUnavailableError,
)
from app.operations.application.recovery.planning.operational_recovery_paths import (
    active_lock_path,
    manifest_path,
    manifest_path_by_id,
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
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_dict_default
from app.shared.serialization.model_codec import schema_payload
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject


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

    @classmethod
    def unreadable(cls) -> RecoveryActiveLockPayload:
        """Build a fail-closed sentinel payload when the active lock file is unreadable.

        Returns:
            Unreadable sentinel active lock payload.
        """
        return cls(
            run_id=UNREADABLE_ACTIVE_RECOVERY_RUN_ID,
            read_error="active_recovery_lock_unreadable",
        )


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
        Field(
            description="Markdown manifest for this recovery source snapshot payload."
        ),
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
        JSONObject, Field(description="Result for this recovery step result payload.")
    ] = schema_dict_default()


class RecoveryRunManifestPayload(RecoveryPersistencePayload):
    """Validated complete recovery run manifest."""

    id: str
    parent_run_id: str | None = None
    idempotency_key: str
    admitted_plan_hash: str | None = None
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
        Field(description="Diagnosis for this recovery run manifest payload."),
    ] = ()
    planned_steps: Annotated[
        tuple[RecoveryPlanStepPayload, ...],
        Field(description="Planned steps for this recovery run manifest payload."),
    ] = ()
    step_results: Annotated[
        tuple[RecoveryStepResultPayload, ...],
        Field(description="Step results for this recovery run manifest payload."),
    ] = ()
    rebuild_results: Annotated[
        JSONObject,
        Field(description="Rebuild results for this recovery run manifest payload."),
    ] = schema_dict_default()
    verification_results: Annotated[
        JSONObject,
        Field(
            description="Verification results for this recovery run manifest payload."
        ),
    ] = schema_dict_default()
    error_code: str | None = None
    error_summary: str | None = None
    next_actions: Annotated[
        tuple[str, ...],
        Field(description="Next actions for this recovery run manifest payload."),
    ] = ()

    @classmethod
    def from_entity(cls, run: RecoveryRun) -> RecoveryRunManifestPayload:
        """Convert a RecoveryRun entity into a validated persistence payload.

        Args:
            run: RecoveryRun domain entity to serialize.

        Returns:
            Validated RecoveryRunManifestPayload instance.
        """
        snap = run.source_snapshot
        return cls(
            id=run.id,
            parent_run_id=run.parent_run_id,
            idempotency_key=run.idempotency_key,
            admitted_plan_hash=run.admitted_plan_hash,
            trigger=run.trigger,
            actor=run.actor,
            status=run.status,
            current_step=run.current_step,
            started_at=run.started_at,
            updated_at=run.updated_at,
            finished_at=run.finished_at,
            source_snapshot=RecoverySourceSnapshotPayload(
                vault_path=snap.vault_path,
                alexandria_root=snap.alexandria_root,
                managed_markdown_count=snap.managed_markdown_count,
                representative_path=snap.representative_path,
                representative_sha256=snap.representative_sha256,
                disk_free_bytes=snap.disk_free_bytes,
                access_error=snap.access_error,
                markdown_manifest=dict(snap.markdown_manifest),
            ),
            diagnosis=tuple(run.diagnosis),
            planned_steps=tuple(
                RecoveryPlanStepPayload(
                    code=step.code, title=step.title, mutates_state=step.mutates_state
                )
                for step in run.planned_steps
            ),
            step_results=tuple(
                RecoveryStepResultPayload(
                    code=step.code,
                    status=step.status,
                    attempts=step.attempts,
                    started_at=step.started_at,
                    finished_at=step.finished_at,
                    input_hash=step.input_hash,
                    result=step.result,
                )
                for step in run.step_results
            ),
            rebuild_results=run.rebuild_results,
            verification_results=run.verification_results,
            error_code=run.error_code,
            error_summary=run.error_summary,
            next_actions=tuple(run.next_actions),
        )

    def to_entity(self, manifest_path_str: str) -> RecoveryRun:
        """Reconstruct a RecoveryRun domain entity from a validated manifest payload.

        Args:
            manifest_path_str: Filesystem path where the manifest was loaded from.

        Returns:
            Reconstructed RecoveryRun domain entity.
        """
        snap = self.source_snapshot
        return RecoveryRun(
            id=self.id,
            parent_run_id=self.parent_run_id,
            idempotency_key=self.idempotency_key,
            admitted_plan_hash=self.admitted_plan_hash,
            trigger=self.trigger,
            actor=self.actor,
            status=RecoveryRunStatus(self.status),
            current_step=self.current_step,
            started_at=self.started_at,
            updated_at=self.updated_at,
            finished_at=self.finished_at,
            source_snapshot=RecoverySourceSnapshot(
                vault_path=snap.vault_path,
                alexandria_root=snap.alexandria_root,
                managed_markdown_count=snap.managed_markdown_count,
                representative_path=snap.representative_path,
                representative_sha256=snap.representative_sha256,
                disk_free_bytes=snap.disk_free_bytes,
                access_error=snap.access_error,
                markdown_manifest=dict(snap.markdown_manifest),
            ),
            diagnosis=tuple(self.diagnosis),
            planned_steps=tuple(
                RecoveryPlanStep(
                    code=item.code, title=item.title, mutates_state=item.mutates_state
                )
                for item in self.planned_steps
            ),
            step_results=tuple(
                RecoveryRunStepResult(
                    code=item.code,
                    status=RecoveryStepStatus(item.status),
                    attempts=item.attempts,
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                    input_hash=item.input_hash,
                    result=item.result,
                )
                for item in self.step_results
            ),
            rebuild_results=self.rebuild_results,
            verification_results=self.verification_results,
            error_code=self.error_code,
            error_summary=self.error_summary,
            next_actions=tuple(self.next_actions),
            manifest_path=manifest_path_str,
        )


class RecoveryActiveLockStore:
    """Coordinate durable active recovery lock acquisition, step updates, and release."""

    @staticmethod
    def read() -> RecoveryActiveLockPayload | None:
        """Read and validate the active recovery lock record if present.

        Returns:
            Validated active lock payload, an unreadable sentinel payload on parse/IO
            errors, or None when no active lock file exists.
        """
        path = active_lock_path()
        if not path.exists():
            return None
        try:
            return RecoveryActiveLockPayload.model_validate_json(path.read_bytes())
        except OSError, ValueError, ValidationError:
            return RecoveryActiveLockPayload.unreadable()

    @staticmethod
    def write(plan: RecoveryPlan) -> None:
        """Acquire the active recovery lock for a plan under the record guard.

        Args:
            plan: Recovery plan claiming the active recovery lock.

        Raises:
            RecoveryInProgressError: If an active recovery lock already exists.
        """
        with _active_record_guard():
            existing = RecoveryActiveLockStore.read()
            if existing is not None:
                raise RecoveryInProgressError(existing.run_id, existing.idempotency_key)
            RecoveryActiveLockStore.write_record(plan)

    @staticmethod
    def write_record(
        plan: RecoveryPlan,
        *,
        started_at: datetime | None = None,
    ) -> None:
        """Write the active lock payload while the caller owns the record guard.

        Args:
            plan: Recovery plan owning the active recovery lock.
            started_at: Optional explicit start timestamp for the lock record.
        """
        payload = RecoveryActiveLockPayload(
            run_id=plan.id,
            idempotency_key=plan.idempotency_key,
            trigger=plan.trigger,
            actor=plan.actor,
            started_at=started_at or datetime.now(UTC),
        )
        _write_recovery_record(
            active_lock_path(), dumps_pretty_json(schema_payload(payload))
        )

    @staticmethod
    def checkpoint_step(plan: RecoveryPlan, current_step: str) -> str:
        """Record the currently executing step in the active lock under the guard.

        Args:
            plan: Admitted recovery plan owning the active lock.
            current_step: Step code about to execute.

        Returns:
            The checkpointed step code.

        Raises:
            RecoveryInProgressError: If the active lock is missing or owned by another run.
        """
        with _active_record_guard():
            payload = RecoveryActiveLockStore.read()
            if payload is None or payload.run_id != plan.id:
                raise RecoveryInProgressError(
                    UNREADABLE_ACTIVE_RECOVERY_RUN_ID
                    if payload is None
                    else payload.run_id,
                    None if payload is None else payload.idempotency_key,
                )
            payload = payload.model_copy(
                update={"current_step": current_step, "updated_at": datetime.now(UTC)}
            )
            _write_recovery_record(
                active_lock_path(), dumps_pretty_json(schema_payload(payload))
            )
        return current_step

    @staticmethod
    def clear(plan: RecoveryPlan) -> None:
        """Release the active recovery lock if still owned by the given plan.

        Args:
            plan: Recovery plan whose active lock should be cleared.
        """
        with _active_record_guard():
            path = active_lock_path()
            payload = RecoveryActiveLockStore.read()
            if payload is None or payload.run_id != plan.id:
                return
            path.unlink()
            _sync_recovery_directory(path.parent)


class RecoveryManifestStore:
    """Persist and admit recovery run manifests under the active-record guard."""

    @staticmethod
    def write(run: RecoveryRun) -> None:
        """Persist the complete recovery run manifest atomically.

        Args:
            run: Recovery run state to serialize to its manifest path.
        """
        path = Path(run.manifest_path)
        _write_recovery_record(
            path,
            dumps_pretty_json(
                schema_payload(RecoveryRunManifestPayload.from_entity(run))
            ),
        )

    @staticmethod
    def read(path: Path) -> RecoveryRun:
        """Load and validate a recovery run from its JSON manifest file.

        Args:
            path: Filesystem path to the recovery-run.json manifest.

        Returns:
            Reconstructed RecoveryRun domain entity.
        """
        payload = RecoveryRunManifestPayload.model_validate_json(path.read_bytes())
        return payload.to_entity(str(path))

    @staticmethod
    def admit(
        plan: RecoveryPlan,
        prepared_run: RecoveryRun,
    ) -> tuple[RecoveryRun, bool]:
        """Replay or admit a run under the existing active-record guard.

        Rechecking both durable records while holding the guard closes the gap
        between a caller's initial lookup and its admission. A RUNNING prepared
        record claims admission; a BLOCKED record is persisted without a claim.

        Args:
            plan: Current plan whose idempotency identity is being admitted.
            prepared_run: RUNNING admission evidence or a preflight BLOCKED result.

        Returns:
            The durable run and whether it was replayed from an existing manifest.

        Raises:
            RecoveryInProgressError: When another recovery run owns the active lock.
            RecoveryRunObservationUnavailableError: When an existing manifest for
                the plan cannot be read or validated safely.
        """
        with _active_record_guard():
            path = manifest_path(plan)
            if path.exists():
                try:
                    recorded: RecoveryRun | None = RecoveryManifestStore.read(path)
                except (OSError, ValueError, ValidationError) as exc:
                    raise RecoveryRunObservationUnavailableError(plan.id) from exc
            else:
                recorded = None
            active_lock = RecoveryActiveLockStore.read()
            if recorded is not None:
                return recorded, True
            if active_lock is not None:
                raise RecoveryInProgressError(
                    active_lock.run_id,
                    active_lock.idempotency_key,
                )

            try:
                RecoveryManifestStore.write(prepared_run)
            except OSError:
                path.unlink(missing_ok=True)
                raise
            if prepared_run.status is RecoveryRunStatus.RUNNING:
                try:
                    RecoveryActiveLockStore.write_record(
                        plan, started_at=prepared_run.started_at
                    )
                except OSError:
                    try:
                        active_lock_path().unlink(missing_ok=True)
                    finally:
                        path.unlink(missing_ok=True)
                    raise
            return prepared_run, False


@contextmanager
def _active_record_guard() -> Generator[None]:
    """Fence admission and conditional updates of the existing active record.

    Yields:
        Control while the process holds the exclusive active-record guard lock.
    """
    directory = _recovery_dir()
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "active-run.guard", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        flock(descriptor, LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _write_recovery_record(path: Path, content: bytes) -> None:
    """Durably replace one complete recovery record without a truncated read window.

    Args:
        path: Target file path for the recovery record.
        content: Serialized record bytes to write and fsync.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_recovery_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _sync_recovery_directory(path: Path) -> None:
    """Persist recovery record rename or removal in its parent directory.

    Args:
        path: Directory path to fsync.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = (
    "RecoveryActiveLockPayload",
    "RecoveryActiveLockStore",
    "RecoveryManifestStore",
    "RecoveryPersistencePayload",
    "RecoveryPlanStepPayload",
    "RecoveryRunManifestPayload",
    "RecoverySourceSnapshotPayload",
    "RecoveryStepResultPayload",
    "active_lock_path",
    "manifest_path",
    "manifest_path_by_id",
)
