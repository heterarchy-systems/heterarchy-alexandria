"""Manual operational recovery run execution service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

import anyio

from app.memory.application.contexts.records.context_service_ports import (
    ContextRecoveryPort,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianRecoveryPort
from app.operations.application.readiness.operational_readiness_service import (
    GraphProjectionReadinessPort,
)
from app.operations.application.recovery.execution.recovery_run_contracts import (
    ContextRecoveryPortFactory,
    ObsidianRecoveryPortFactory,
)
from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
    RecoveryStepFailedError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    _checkpoint_active_step,
    _clear_active_lock,
    _clear_active_lock_for_run_id,
    _manifest_path,
    _manifest_path_by_id,
    _read_active_lock,
    _run_from_manifest,
    _write_active_lock,
    _write_manifest,
)
from app.operations.application.recovery.execution.recovery_run_mutation_operations import (
    RecoveryRunMutationOperations,
)
from app.operations.application.recovery.execution.recovery_run_retry_policy import (
    _blocked_run,
    _default_retry_idempotency_key,
    _interrupted_active_run,
    _parent_run_for_retry,
    _successful_parent_steps,
)
from app.operations.application.recovery.execution.recovery_run_source_preservation import (
    _snapshot_sources,
    _source_snapshot_from_vault,
)
from app.operations.application.recovery.execution.recovery_run_step_execution import (
    _execute_or_skip_step,
    _require_empty_result_list,
    _require_step_success,
)
from app.operations.application.recovery.execution.recovery_run_verification_service import (
    RecoveryRunVerificationService,
)
from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.application.recovery.planning.recovery_plan_service import (
    RecoveryPlanService,
)
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
    RecoveryRunStepResult,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
)
from app.shared.infrastructure.database import Database
from app.shared.types.extra_types import JSONObject

__all__ = (
    "ContextRecoveryPort",
    "ObsidianRecoveryPort",
    "RecoveryInProgressError",
    "RecoveryRunService",
    "RecoveryStepFailedError",
)


class RecoveryRunService:
    """Coordinate one recovery run lifecycle.

    The class keeps recovery step orchestration together because each private step
    participates in the same ordered run state machine. Active-lock and manifest
    persistence are delegated to ``recovery_run_manifest``.
    """

    def __init__(
        self,
        database: Database,
        context_service: ContextRecoveryPort,
        obsidian_service: ObsidianRecoveryPort,
        context_service_factory: ContextRecoveryPortFactory | None = None,
        obsidian_service_factory: ObsidianRecoveryPortFactory | None = None,
        *,
        graph_projection_service: GraphProjectionReadinessPort,
    ) -> None:
        """Create service.

        Args:
            database: Shared database coordinator.
            context_service: Context/RAG service.
            obsidian_service: Obsidian vault service.
            context_service_factory: Factory that creates context service.
            obsidian_service_factory: Factory that creates obsidian service.
            graph_projection_service: Graph projection status boundary.
        """
        self._database = database
        self._context_service = context_service
        self._obsidian_service = obsidian_service
        self._mutations = RecoveryRunMutationOperations(
            database=database,
            context_service=context_service,
            obsidian_service=obsidian_service,
            context_service_factory=context_service_factory,
            obsidian_service_factory=obsidian_service_factory,
        )
        self._graph_projection_service = graph_projection_service
        self._verification = RecoveryRunVerificationService(
            database=database,
            context_service=context_service,
            obsidian_service=obsidian_service,
            context_service_factory=context_service_factory,
            obsidian_service_factory=obsidian_service_factory,
            graph_projection_service=graph_projection_service,
        )

    async def start(self, request: RecoveryPlanRequest) -> RecoveryRun:
        """Start or return an idempotent manual recovery run.

        Args:
            request: Recovery plan/start request.

        Returns:
            Executed or previously stored recovery run.
        """
        plan = await RecoveryPlanService(
            database=self._database,
            context_service=self._context_service,
            obsidian_service=self._obsidian_service,
            graph_projection_service=self._graph_projection_service,
        ).plan(request)
        manifest_path = _manifest_path(plan)
        if manifest_path.exists():
            return _run_from_manifest(manifest_path)
        active_lock = await _record_io(_read_active_lock)
        if active_lock is not None:
            raise RecoveryInProgressError(
                run_id=active_lock.run_id,
                idempotency_key=active_lock.idempotency_key,
            )
        if not plan.automatic_execution_allowed:
            run = _blocked_run(plan=plan, manifest_path=manifest_path)
            await _record_io(partial(_write_manifest, run))
            return run

        parent_run = _parent_run_for_retry(parent_run_id=request.parent_run_id)
        parent_success_steps = _successful_parent_steps(parent_run)

        await _record_io(partial(_write_active_lock, plan))
        started_at = datetime.now(UTC)
        step_results: list[RecoveryRunStepResult] = []
        rebuild_results: JSONObject = {}
        verification_results: JSONObject = {}
        error_code: str | None = None
        error_summary: str | None = None
        status = RecoveryRunStatus.RUNNING
        current_step: str | None = None
        try:
            for planned_step in plan.steps:
                current_step = await _record_io(
                    partial(_checkpoint_active_step, plan, planned_step.code)
                )
                if current_step == "snapshot_sources":
                    result = await _execute_or_skip_step(
                        current_step,
                        lambda: _snapshot_sources(plan),
                        parent_run=parent_run,
                        parent_success_steps=parent_success_steps,
                    )
                elif current_step == "reindex_vault":
                    result = await _execute_or_skip_step(
                        current_step,
                        self._mutations.reindex_vault,
                        parent_run=parent_run,
                        parent_success_steps=parent_success_steps,
                    )
                    rebuild_results["vault"] = result.result
                    _require_step_success(result, error_code="VAULT_REINDEX_FAILED")
                    _require_empty_result_list(
                        result,
                        key="errors",
                        error_code="VAULT_REINDEX_FAILED",
                    )
                elif current_step == "reindex_embeddings":
                    result = await _execute_or_skip_step(
                        current_step,
                        self._mutations.reindex_embeddings,
                        parent_run=parent_run,
                        parent_success_steps=parent_success_steps,
                    )
                    rebuild_results["embeddings"] = result.result
                    _require_step_success(
                        result,
                        error_code="EMBEDDING_REINDEX_FAILED",
                    )
                    _require_empty_result_list(
                        result,
                        key="warnings",
                        error_code="EMBEDDING_REINDEX_REQUIRED",
                    )
                elif current_step == "verify_readiness":
                    result = await _execute_or_skip_step(
                        current_step,
                        lambda: self._verification.verify_readiness(plan),
                        parent_run=parent_run,
                        parent_success_steps=parent_success_steps,
                    )
                    verification_results = result.result
                    if verification_results.get("ready") is not True:
                        raise RecoveryStepFailedError(
                            error_code="READINESS_VERIFICATION_FAILED",
                            error_summary="Operational readiness did not become READY.",
                        )
                else:
                    raise RecoveryStepFailedError(
                        error_code="UNSUPPORTED_RECOVERY_STEP",
                        error_summary=f"Unsupported recovery step: {current_step}",
                    )
                step_results.append(result)
            status = RecoveryRunStatus.COMPLETED
        except RecoveryStepFailedError as exc:
            status = RecoveryRunStatus.FAILED
            error_code = exc.error_code
            error_summary = exc.error_summary
        except Exception as exc:
            status = RecoveryRunStatus.FAILED
            error_code = "RECOVERY_RUN_FAILED"
            error_summary = str(exc)
        finished_at = datetime.now(UTC)
        run = RecoveryRun(
            id=plan.id,
            parent_run_id=plan.parent_run_id,
            idempotency_key=plan.idempotency_key,
            trigger=plan.trigger,
            actor=plan.actor,
            status=status,
            current_step=current_step,
            started_at=started_at,
            updated_at=finished_at,
            finished_at=finished_at,
            source_snapshot=plan.source_snapshot,
            diagnosis=plan.diagnosis,
            planned_steps=plan.steps,
            step_results=tuple(step_results),
            rebuild_results=rebuild_results,
            verification_results=verification_results,
            error_code=error_code,
            error_summary=error_summary,
            next_actions=()
            if status is RecoveryRunStatus.COMPLETED
            else ("inspect_recovery_run",),
            manifest_path=str(manifest_path),
        )
        await _record_io(partial(_write_manifest, run))
        await _record_io(partial(_clear_active_lock, plan))
        return run

    async def get(self, run_id: str) -> RecoveryRun | None:
        """Return a persisted recovery run by id.

        Args:
            run_id: Recovery run identifier.

        Returns:
            Recovery run from manifest, or None when it is unknown.
        """
        manifest_path = _manifest_path_by_id(run_id=run_id)
        if not manifest_path.exists():
            active_lock = await _record_io(_read_active_lock)
            if active_lock is not None and active_lock.run_id == run_id:
                vault_status = await self._obsidian_service.status()
                run = _interrupted_active_run(
                    active_lock=active_lock,
                    source_snapshot=_source_snapshot_from_vault(
                        vault_path=vault_status.vault_path,
                        alexandria_root=vault_status.alexandria_root,
                    ),
                    manifest_path=manifest_path,
                )
                await _record_io(partial(_write_manifest, run))
                await _record_io(partial(_clear_active_lock_for_run_id, run_id=run_id))
                return run
            return None
        return _run_from_manifest(manifest_path)

    async def retry(
        self,
        parent_run_id: str,
        request: RecoveryPlanRequest,
    ) -> RecoveryRun | None:
        """Start a parent-linked retry recovery run.

        Args:
            parent_run_id: Recovery run id to retry.
            request: Retry request input.

        Returns:
            New or idempotent retry run, or None when the parent is unknown.
        """
        parent_run = await self.get(parent_run_id)
        if parent_run is None:
            return None
        retry_request = RecoveryPlanRequest(
            trigger=request.trigger,
            actor=request.actor,
            idempotency_key=request.idempotency_key
            or _default_retry_idempotency_key(parent_run_id),
            parent_run_id=parent_run_id,
        )
        return await self.start(retry_request)


async def _record_io[T](operation: Callable[[], T]) -> T:
    """Run recovery record effects on the bounded framework worker lane."""
    return await anyio.to_thread.run_sync(
        operation, limiter=anyio.to_thread.current_default_thread_limiter()
    )
