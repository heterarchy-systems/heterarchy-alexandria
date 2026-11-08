"""Manual operational recovery run execution service."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from functools import partial

from pydantic import ValidationError

from app.memory.application.contexts.records.context_service_ports import (
    ContextRecoveryPort,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianRecoveryPort
from app.operations.application.readiness.operational_readiness_service import (
    GraphProjectionReadinessPort,
)
from app.operations.application.recovery.execution.recovery_run_contracts import (
    ContextRecoveryPortFactory,
    EmbeddingRecoveryCallback,
    ObsidianRecoveryPortFactory,
    RecoveryDiagnosticCallback,
)
from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
    RecoveryRunNotRetryableError,
    RecoveryRunObservationUnavailableError,
    RecoveryStepFailedError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    RecoveryActiveLockStore,
    RecoveryManifestStore,
    manifest_path,
    manifest_path_by_id,
)
from app.operations.application.recovery.execution.recovery_run_mutation_operations import (
    RecoveryRunMutationOperations,
)
from app.operations.application.recovery.execution.recovery_run_retry_policy import (
    blocked_run,
    default_retry_idempotency_key,
    parent_run_for_retry,
    successful_parent_steps,
)
from app.operations.application.recovery.execution.recovery_run_verification_service import (
    RecoveryRunVerificationService,
)
from app.operations.application.recovery.execution.steps.recovery_step_executor import (
    RecoveryStepExecutor,
)
from app.operations.application.recovery.planning.recovery_plan_contracts import (
    RecoveryPlanRequest,
)
from app.operations.application.recovery.planning.recovery_plan_service import (
    RecoveryPlanService,
)
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
)
from app.operations.domain.event_enum.recovery_step_enums import (
    RecoveryNextAction,
    RecoveryStepErrorCode,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.infrastructure.database import Database

__all__ = (
    "ContextRecoveryPort",
    "ObsidianRecoveryPort",
    "RecoveryInProgressError",
    "RecoveryRunService",
    "RecoveryStepFailedError",
)


class RecoveryRunService:
    """Coordinate one recovery run lifecycle.

    Admission, active-lock, and manifest persistence are delegated to
    ``recovery_run_manifest``, while ordered step execution is delegated to
    ``RecoveryStepExecutor``.
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
        embedding_recovery_callback: EmbeddingRecoveryCallback | None = None,
        graph_rebuild_callback: RecoveryDiagnosticCallback | None = None,
        link_diagnostics_callback: RecoveryDiagnosticCallback | None = None,
        dlq_reconcile_callback: RecoveryDiagnosticCallback | None = None,
        current_compact_reader_callback: RecoveryDiagnosticCallback | None = None,
        embedding_batch_size: int = 250,
        embedding_max_batches: int = 40,
    ) -> None:
        """Create service.

        Args:
            database: Shared database coordinator.
            context_service: Context/RAG service.
            obsidian_service: Obsidian vault service.
            context_service_factory: Factory that creates context service.
            obsidian_service_factory: Factory that creates obsidian service.
            graph_projection_service: Graph projection status boundary.
            embedding_recovery_callback: Optional embedding recovery callback.
            graph_rebuild_callback: Optional graph projection rebuild callback.
            link_diagnostics_callback: Optional link diagnostics callback.
            dlq_reconcile_callback: Optional dead-letter reconciliation callback.
            current_compact_reader_callback: Optional CURRENT Compact reader callback.
            embedding_batch_size: Maximum embeddings processed per batch.
            embedding_max_batches: Maximum batches processed per recovery step.
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
            embedding_recovery_callback=embedding_recovery_callback,
            graph_rebuild_callback=graph_rebuild_callback,
            link_diagnostics_callback=link_diagnostics_callback,
            dlq_reconcile_callback=dlq_reconcile_callback,
            embedding_batch_size=embedding_batch_size,
            embedding_max_batches=embedding_max_batches,
        )
        self._graph_projection_service = graph_projection_service
        self._verification = RecoveryRunVerificationService(
            database=database,
            context_service=context_service,
            obsidian_service=obsidian_service,
            context_service_factory=context_service_factory,
            obsidian_service_factory=obsidian_service_factory,
            graph_projection_service=graph_projection_service,
            current_compact_reader_callback=current_compact_reader_callback,
        )
        self._embedding_recovery_callback = embedding_recovery_callback
        self._graph_rebuild_callback = graph_rebuild_callback
        self._link_diagnostics_callback = link_diagnostics_callback
        self._dlq_reconcile_callback = dlq_reconcile_callback
        self._current_compact_reader_callback = current_compact_reader_callback

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
            embedding_recovery_callback=self._embedding_recovery_callback,
            graph_rebuild_callback=self._graph_rebuild_callback,
            link_diagnostics_callback=self._link_diagnostics_callback,
            dlq_reconcile_callback=self._dlq_reconcile_callback,
            current_compact_reader_callback=self._current_compact_reader_callback,
        ).plan(request)
        run_manifest_path = manifest_path(plan)
        prepared_run: RecoveryRun
        if not plan.automatic_execution_allowed:
            prepared_run = blocked_run(plan=plan, manifest_path=run_manifest_path)
        elif request.expected_plan_hash != plan.plan_hash:
            # Apply fence: source revision drifted between dry-run and apply,
            # so the agent must re-plan instead of applying a stale plan.
            prepared_run = blocked_run(plan=plan, manifest_path=run_manifest_path)
            prepared_run.error_code = RecoveryStepErrorCode.RECOVERY_PLAN_DRIFT.value
            prepared_run.error_summary = (
                "expected_plan_hash does not match the current plan hash; "
                "re-plan before applying"
            )
        else:
            started_at = datetime.now(UTC)
            prepared_run = RecoveryRun(
                id=plan.id,
                parent_run_id=plan.parent_run_id,
                idempotency_key=plan.idempotency_key,
                admitted_plan_hash=plan.plan_hash,
                trigger=plan.trigger,
                actor=plan.actor,
                status=RecoveryRunStatus.RUNNING,
                current_step=None,
                started_at=started_at,
                updated_at=started_at,
                finished_at=None,
                source_snapshot=plan.source_snapshot,
                diagnosis=plan.diagnosis,
                planned_steps=plan.steps,
                step_results=(),
                rebuild_results={},
                verification_results={},
                error_code=None,
                error_summary=None,
                next_actions=(RecoveryNextAction.INSPECT_RECOVERY_RUN.value,),
                manifest_path=str(run_manifest_path),
            )

        run, replayed = await run_critical_sync(
            partial(RecoveryManifestStore.admit, plan, prepared_run)
        )
        if replayed:
            if (
                request.expected_plan_hash is None
                or request.expected_plan_hash != run.admitted_plan_hash
            ):
                return replace(
                    run,
                    status=RecoveryRunStatus.BLOCKED,
                    error_code=RecoveryStepErrorCode.RECOVERY_PLAN_IDEMPOTENCY_CONFLICT.value,
                    error_summary="The replay does not name the recorded admitted plan; the durable run is unchanged",
                )
            return run
        if run.status is not RecoveryRunStatus.RUNNING:
            return run

        parent_run = await run_critical_sync(
            partial(parent_run_for_retry, parent_run_id=request.parent_run_id)
        )
        parent_success_steps = successful_parent_steps(parent_run)
        started_at = run.started_at
        outcome = await RecoveryStepExecutor(
            mutations=self._mutations,
            verification=self._verification,
        ).execute(
            plan=plan,
            parent_run=parent_run,
            parent_success_steps=parent_success_steps,
        )
        finished_at = datetime.now(UTC)
        run = RecoveryRun(
            id=plan.id,
            parent_run_id=plan.parent_run_id,
            idempotency_key=plan.idempotency_key,
            admitted_plan_hash=plan.plan_hash,
            trigger=plan.trigger,
            actor=plan.actor,
            status=outcome.status,
            current_step=outcome.current_step,
            started_at=started_at,
            updated_at=finished_at,
            finished_at=finished_at,
            source_snapshot=plan.source_snapshot,
            diagnosis=plan.diagnosis,
            planned_steps=plan.steps,
            step_results=outcome.step_results,
            rebuild_results=outcome.rebuild_results,
            verification_results=outcome.verification_results,
            error_code=outcome.error_code,
            error_summary=outcome.error_summary,
            next_actions=()
            if outcome.status is RecoveryRunStatus.COMPLETED
            else (RecoveryNextAction.INSPECT_RECOVERY_RUN.value,),
            manifest_path=str(run_manifest_path),
        )
        await run_critical_sync(partial(RecoveryManifestStore.write, run))
        await run_critical_sync(partial(RecoveryActiveLockStore.clear, plan))
        return run

    async def get(self, run_id: str) -> RecoveryRun | None:
        """Return the last persisted recovery state by id.

        A RUNNING manifest is persisted progress, not proof of a live owner.

        Args:
            run_id: Recovery run identifier.

        Returns:
            Recovery run from manifest, or None when it is unknown.

        Raises:
            RecoveryRunObservationUnavailableError: When the active lock or manifest
                cannot be safely observed.
        """
        run_manifest_path = manifest_path_by_id(run_id=run_id)
        if not run_manifest_path.exists():
            active_lock = await run_critical_sync(RecoveryActiveLockStore.read)
            if active_lock is not None and (
                active_lock.read_error is not None or active_lock.run_id == run_id
            ):
                raise RecoveryRunObservationUnavailableError(run_id)
            return None
        try:
            return await run_critical_sync(
                partial(RecoveryManifestStore.read, run_manifest_path)
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise RecoveryRunObservationUnavailableError(run_id) from exc

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

        Raises:
            RecoveryRunNotRetryableError: When the parent run is still RUNNING.
        """
        parent_run = await self.get(parent_run_id)
        if parent_run is None:
            return None
        if parent_run.status is RecoveryRunStatus.RUNNING:
            raise RecoveryRunNotRetryableError(
                run_id=parent_run.id,
                status=parent_run.status.value,
            )
        retry_request = RecoveryPlanRequest(
            trigger=request.trigger,
            actor=request.actor,
            idempotency_key=request.idempotency_key
            or default_retry_idempotency_key(parent_run_id),
            parent_run_id=parent_run_id,
            expected_plan_hash=request.expected_plan_hash,
        )
        return await self.start(retry_request)
