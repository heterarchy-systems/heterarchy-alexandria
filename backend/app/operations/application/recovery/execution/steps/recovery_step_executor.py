"""Execute ordered recovery plan steps in the recovery run task."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryStepFailedError,
)
from app.operations.application.recovery.execution.recovery_run_manifest import (
    RecoveryActiveLockStore,
)
from app.operations.application.recovery.execution.recovery_run_mutation_operations import (
    RecoveryRunMutationOperations,
)
from app.operations.application.recovery.execution.recovery_run_source_preservation import (
    snapshot_sources,
)
from app.operations.application.recovery.execution.recovery_run_verification_service import (
    RecoveryRunVerificationService,
)
from app.operations.application.recovery.execution.steps.recovery_step_execution import (
    execute_or_skip_step,
    require_empty_result_list,
    require_step_success,
)
from app.operations.domain.entities.recovery_plan import RecoveryPlan
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
    RecoveryRunStepResult,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryRunStatus,
)
from app.operations.domain.event_enum.recovery_step_enums import (
    RecoveryStepCode,
    RecoveryStepErrorCode,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.types.extra_types import JSONObject, JSONValue


async def _snapshot_sources_payload(plan: RecoveryPlan) -> JSONObject:
    """Serialize the typed source snapshot summary for step result persistence.

    Args:
        plan: Admitted recovery plan containing the source snapshot.

    Returns:
        JSONObject representation of the source snapshot summary.
    """
    return dict[str, JSONValue](**(await snapshot_sources(plan)))


@dataclass(frozen=True, slots=True)
class RecoveryExecutionOutcome:
    """Ordered step execution state returned for final run publication."""

    status: RecoveryRunStatus
    current_step: str | None
    step_results: tuple[RecoveryRunStepResult, ...]
    rebuild_results: JSONObject
    verification_results: JSONObject
    error_code: str | None
    error_summary: str | None


@dataclass(slots=True)
class _StepExecutionState:
    """Mutable step accumulator scoped to one RecoveryStepExecutor.execute call."""

    plan: RecoveryPlan
    parent_run: RecoveryRun | None
    parent_success_steps: dict[tuple[str, str], RecoveryRunStepResult]
    step_results: list[RecoveryRunStepResult] = field(default_factory=list)
    rebuild_results: JSONObject = field(default_factory=dict)
    verification_results: JSONObject = field(default_factory=dict)


class RecoveryStepExecutor:
    """Execute one plan using the run's existing mutation and verification owners."""

    def __init__(
        self,
        mutations: RecoveryRunMutationOperations,
        verification: RecoveryRunVerificationService,
    ) -> None:
        """Borrow the mutation and verification owners created by the run service.

        Args:
            mutations: Recovery mutation operations owner.
            verification: Recovery verification service owner.
        """
        self._mutations = mutations
        self._verification = verification

    async def execute(
        self,
        plan: RecoveryPlan,
        parent_run: RecoveryRun | None,
        parent_success_steps: dict[tuple[str, str], RecoveryRunStepResult],
    ) -> RecoveryExecutionOutcome:
        """Run the plan's ordered steps and capture its original failure semantics.

        Args:
            plan: Admitted recovery plan to execute.
            parent_run: Optional parent recovery run for retry step skipping.
            parent_success_steps: Successful parent steps indexed by code and input hash.

        Returns:
            Ordered step execution outcome for final manifest publication.
        """
        state = _StepExecutionState(
            plan=plan,
            parent_run=parent_run,
            parent_success_steps=parent_success_steps,
        )
        error_code: str | None = None
        error_summary: str | None = None
        status = RecoveryRunStatus.RUNNING
        current_step: str | None = None
        try:
            for planned_step in plan.steps:
                current_step = await run_critical_sync(
                    partial(
                        RecoveryActiveLockStore.checkpoint_step,
                        plan,
                        planned_step.code,
                    )
                )
                result, recorded_before_fence = await self._dispatch_step(
                    current_step, state
                )
                if not recorded_before_fence:
                    state.step_results.append(result)
            status = RecoveryRunStatus.COMPLETED
        except RecoveryStepFailedError as exc:
            status = RecoveryRunStatus.FAILED
            error_code = exc.error_code
            error_summary = exc.error_summary
        except Exception as exc:
            status = RecoveryRunStatus.FAILED
            error_code = RecoveryStepErrorCode.RECOVERY_RUN_FAILED.value
            error_summary = str(exc)
        return RecoveryExecutionOutcome(
            status=status,
            current_step=current_step,
            step_results=tuple(state.step_results),
            rebuild_results=state.rebuild_results,
            verification_results=state.verification_results,
            error_code=error_code,
            error_summary=error_summary,
        )

    async def _dispatch_step(
        self,
        current_step: str,
        state: _StepExecutionState,
    ) -> tuple[RecoveryRunStepResult, bool]:
        """Route one checkpointed step code to its dedicated handler.

        Args:
            current_step: Checkpointed step code.
            state: Mutable execution state for the current recovery run.

        Returns:
            Tuple of the step result and whether it was already appended before a fence.

        Raises:
            RecoveryStepFailedError: If `current_step` is not a supported recovery step code.
        """
        if current_step == RecoveryStepCode.SNAPSHOT_SOURCES.value:
            result = await execute_or_skip_step(
                current_step,
                lambda: _snapshot_sources_payload(state.plan),
                parent_run=state.parent_run,
                parent_success_steps=state.parent_success_steps,
            )
            return result, False
        if current_step in {
            RecoveryStepCode.REPAIR_MANAGED_FRONTMATTER.value,
            RecoveryStepCode.REPAIR_ERROR_NOTES.value,
        }:
            return await self._run_note_repair_step(current_step, state), True
        if current_step in {
            RecoveryStepCode.VAULT_REINDEX.value,
            RecoveryStepCode.REINDEX_VAULT.value,
            RecoveryStepCode.EMBEDDING_REINDEX.value,
            RecoveryStepCode.REINDEX_EMBEDDINGS.value,
            RecoveryStepCode.GRAPH_REVALIDATE.value,
        }:
            return await self._run_rebuild_step(current_step, state), False
        if current_step in {
            RecoveryStepCode.CURRENT_READINESS_CHECK.value,
            RecoveryStepCode.VERIFY_READINESS.value,
        }:
            return await self._run_readiness_step(current_step, state), False
        if current_step in {
            RecoveryStepCode.LINK_REVALIDATE.value,
            RecoveryStepCode.DLQ_RECONCILE.value,
        }:
            return await self._run_verification_step(current_step, state), False
        raise RecoveryStepFailedError(
            error_code=RecoveryStepErrorCode.UNSUPPORTED_RECOVERY_STEP.value,
            error_summary=f"Unsupported recovery step: {current_step}",
        )

    async def _run_note_repair_step(
        self,
        current_step: str,
        state: _StepExecutionState,
    ) -> RecoveryRunStepResult:
        """Run managed frontmatter/error-note repair and record partial progress before fencing.

        Args:
            current_step: Checkpointed note-repair step code.
            state: Mutable execution state for the current recovery run.

        Returns:
            Executed or skipped note-repair step result.
        """
        result = await execute_or_skip_step(
            current_step,
            lambda: self._mutations.repair_error_notes(
                state.plan.error_note_repairs,
                state.plan.source_snapshot.markdown_manifest,
            ),
            parent_run=state.parent_run,
            parent_success_steps=state.parent_success_steps,
        )
        state.rebuild_results["error_note_repairs"] = result.result
        state.step_results.append(result)
        require_step_success(
            result,
            error_code=RecoveryStepErrorCode.NOTE_REPAIR_FAILED.value,
        )
        require_empty_result_list(
            result,
            key="requires_manual_repair",
            error_code=RecoveryStepErrorCode.NOTE_REPAIR_REQUIRED.value,
        )
        return result

    async def _run_rebuild_step(
        self,
        current_step: str,
        state: _StepExecutionState,
    ) -> RecoveryRunStepResult:
        """Run vault reindex, embedding reindex, or graph revalidation rebuild steps.

        Args:
            current_step: Checkpointed rebuild step code.
            state: Mutable execution state for the current recovery run.

        Returns:
            Executed or skipped rebuild step result.
        """
        if current_step in {
            RecoveryStepCode.VAULT_REINDEX.value,
            RecoveryStepCode.REINDEX_VAULT.value,
        }:
            result = await execute_or_skip_step(
                current_step,
                self._mutations.reindex_vault,
                parent_run=state.parent_run,
                parent_success_steps=state.parent_success_steps,
            )
            state.rebuild_results["vault"] = result.result
            require_step_success(
                result,
                error_code=RecoveryStepErrorCode.VAULT_REINDEX_FAILED.value,
            )
            require_empty_result_list(
                result,
                key="errors",
                error_code=RecoveryStepErrorCode.VAULT_REINDEX_FAILED.value,
            )
            return result
        if current_step in {
            RecoveryStepCode.EMBEDDING_REINDEX.value,
            RecoveryStepCode.REINDEX_EMBEDDINGS.value,
        }:
            result = await execute_or_skip_step(
                current_step,
                self._mutations.reindex_embeddings,
                parent_run=state.parent_run,
                parent_success_steps=state.parent_success_steps,
            )
            state.rebuild_results["embeddings"] = result.result
            require_step_success(
                result,
                error_code=RecoveryStepErrorCode.EMBEDDING_REINDEX_FAILED.value,
            )
            return result
        result = await execute_or_skip_step(
            current_step,
            self._mutations.revalidate_graph,
            parent_run=state.parent_run,
            parent_success_steps=state.parent_success_steps,
        )
        state.rebuild_results["graph"] = result.result
        require_step_success(
            result,
            error_code=RecoveryStepErrorCode.GRAPH_REVALIDATE_FAILED.value,
        )
        require_empty_result_list(
            result,
            key="errors",
            error_code=RecoveryStepErrorCode.GRAPH_REVALIDATE_FAILED.value,
        )
        return result

    async def _run_readiness_step(
        self,
        current_step: str,
        state: _StepExecutionState,
    ) -> RecoveryRunStepResult:
        """Run operational readiness verification with compile-receipt fencing.

        Args:
            current_step: Checkpointed readiness verification step code.
            state: Mutable execution state for the current recovery run.

        Returns:
            Executed or skipped readiness verification step result.

        Raises:
            RecoveryStepFailedError: If compile receipt evidence is missing or readiness is not READY.
        """
        vault_result = state.rebuild_results.get("vault")
        compile_required = False
        expected_policy_version: str | None = None
        expected_plan_fingerprint: str | None = None
        if isinstance(vault_result, dict):
            raw_policy = vault_result.get("policy_version")
            raw_plan = vault_result.get("plan_fingerprint")
            if isinstance(raw_policy, str) and raw_policy:
                expected_policy_version = raw_policy
            if isinstance(raw_plan, str) and raw_plan:
                expected_plan_fingerprint = raw_plan
            compile_required = True
            if expected_policy_version is None or expected_plan_fingerprint is None:
                raise RecoveryStepFailedError(
                    error_code=RecoveryStepErrorCode.COMPILE_RECEIPT_EVIDENCE_MISSING.value,
                    error_summary=(
                        "Vault reindex completed without native compile "
                        "plan and policy evidence"
                    ),
                )
        result = await execute_or_skip_step(
            current_step,
            lambda compile_required=compile_required, expected_policy_version=expected_policy_version, expected_plan_fingerprint=expected_plan_fingerprint: (
                self._verification.verify_readiness(
                    state.plan,
                    compile_receipt_required=compile_required,
                    expected_compile_policy_version=expected_policy_version,
                    expected_compile_plan_fingerprint=expected_plan_fingerprint,
                )
            ),
            parent_run=state.parent_run,
            parent_success_steps=state.parent_success_steps,
        )
        state.verification_results = {**state.verification_results, **result.result}
        if state.verification_results.get("ready") is not True:
            raise RecoveryStepFailedError(
                error_code=RecoveryStepErrorCode.READINESS_VERIFICATION_FAILED.value,
                error_summary="Operational readiness did not become READY.",
            )
        return result

    async def _run_verification_step(
        self,
        current_step: str,
        state: _StepExecutionState,
    ) -> RecoveryRunStepResult:
        """Run link revalidation or dead-letter queue reconciliation steps.

        Args:
            current_step: Checkpointed verification step code.
            state: Mutable execution state for the current recovery run.

        Returns:
            Executed or skipped verification step result.

        Raises:
            RecoveryStepFailedError: If DLQ reconciliation reports unresolved entries.
        """
        if current_step == RecoveryStepCode.LINK_REVALIDATE.value:
            result = await execute_or_skip_step(
                current_step,
                self._mutations.revalidate_links,
                parent_run=state.parent_run,
                parent_success_steps=state.parent_success_steps,
            )
            state.verification_results["links"] = result.result
            require_step_success(
                result,
                error_code=RecoveryStepErrorCode.LINK_REVALIDATE_FAILED.value,
            )
            require_empty_result_list(
                result,
                key="issues",
                error_code=RecoveryStepErrorCode.LINK_REVALIDATE_FAILED.value,
            )
            return result
        result = await execute_or_skip_step(
            current_step,
            self._mutations.reconcile_dead_letters,
            parent_run=state.parent_run,
            parent_success_steps=state.parent_success_steps,
        )
        state.verification_results["dlq"] = result.result
        require_step_success(
            result,
            error_code=RecoveryStepErrorCode.DLQ_RECONCILE_FAILED.value,
        )
        if result.result.get("ready") is not True:
            raise RecoveryStepFailedError(
                error_code=RecoveryStepErrorCode.DLQ_RECONCILIATION_REQUIRED.value,
                error_summary="Unresolved DLQ evidence requires reconciliation before dependent recovery.",
            )
        return result
