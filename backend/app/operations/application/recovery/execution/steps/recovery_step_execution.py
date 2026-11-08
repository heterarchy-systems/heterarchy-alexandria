"""Ordered recovery step execution and validation policies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256

from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryStepFailedError,
)
from app.operations.domain.entities.recovery_run import (
    RecoveryRun,
    RecoveryRunStepResult,
)
from app.operations.domain.event_enum.operational_recovery_enums import (
    RecoveryStepStatus,
)
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject

StepCallable = Callable[[], Awaitable[JSONObject]]


async def execute_or_skip_step(
    code: str,
    callback: StepCallable,
    parent_run: RecoveryRun | None,
    parent_success_steps: dict[tuple[str, str], RecoveryRunStepResult],
    input_payload: JSONObject | None = None,
) -> RecoveryRunStepResult:
    """Run one recovery step or reuse a matching succeeded parent-run step.

    Args:
        code: Canonical recovery step code.
        callback: Async step action returning step result metadata.
        parent_run: Optional parent recovery run when retrying.
        parent_success_steps: Succeeded parent steps indexed by code and input hash.
        input_payload: Optional deterministic input payload hashed for retry matching.

    Returns:
        Executed or skipped recovery step result.
    """
    input_hash = _step_input_hash(code=code, input_payload=input_payload)
    parent_step = parent_success_steps.get((code, input_hash))
    if parent_run is not None and parent_step is not None:
        now = datetime.now(UTC)
        result: JSONObject = {
            **parent_step.result,
            "skipped_from_parent_run_id": parent_run.id,
            "skipped_parent_step_status": parent_step.status.value,
        }
        return RecoveryRunStepResult(
            code=code,
            status=RecoveryStepStatus.SKIPPED,
            attempts=0,
            started_at=now,
            finished_at=now,
            input_hash=input_hash,
            result=result,
        )
    return await _execute_step(code, callback, input_payload=input_payload)


async def _execute_step(
    code: str,
    callback: StepCallable,
    input_payload: JSONObject | None = None,
) -> RecoveryRunStepResult:
    """Invoke a recovery step callback and capture timing and failure state.

    Args:
        code: Canonical recovery step code.
        callback: Async step action returning step result metadata.
        input_payload: Optional deterministic input payload hashed for retry matching.

    Returns:
        Completed or failed recovery step result.
    """
    started_at = datetime.now(UTC)
    input_hash = _step_input_hash(code=code, input_payload=input_payload)
    try:
        result = await callback()
        status = RecoveryStepStatus.SUCCEEDED
    except Exception as exc:
        result: JSONObject = {"error": str(exc)}
        status = RecoveryStepStatus.FAILED
        finished_at = datetime.now(UTC)
        return RecoveryRunStepResult(
            code=code,
            status=status,
            attempts=1,
            started_at=started_at,
            finished_at=finished_at,
            input_hash=input_hash,
            result=result,
        )
    finished_at = datetime.now(UTC)
    return RecoveryRunStepResult(
        code=code,
        status=status,
        attempts=1,
        started_at=started_at,
        finished_at=finished_at,
        input_hash=input_hash,
        result=result,
    )


def _step_input_hash(
    code: str,
    input_payload: JSONObject | None,
) -> str:
    """Compute a deterministic SHA-256 digest over a step code and input payload.

    Args:
        code: Canonical recovery step code.
        input_payload: Optional input payload dictionary for the step.

    Returns:
        Hex-encoded SHA-256 digest identifying the step invocation input.
    """
    payload: JSONObject = {"code": code, "input": input_payload or {}}
    return sha256(dumps_pretty_json(payload)).hexdigest()


def require_step_success(
    step: RecoveryRunStepResult,
    error_code: str,
) -> None:
    """Raise a typed step failure if the step did not succeed or skip.

    Args:
        step: Step result to inspect.
        error_code: Typed error code to emit on failure.

    Raises:
        RecoveryStepFailedError: If the step status is neither SUCCEEDED nor SKIPPED.
    """
    if step.status in {RecoveryStepStatus.SUCCEEDED, RecoveryStepStatus.SKIPPED}:
        return
    raise RecoveryStepFailedError(
        error_code=error_code,
        error_summary=f"{step.code} failed",
    )


def require_empty_result_list(
    step: RecoveryRunStepResult,
    key: str,
    error_code: str,
) -> None:
    """Raise a typed step failure if the step result contains a non-empty list at key.

    Args:
        step: Step result whose payload dictionary is inspected.
        key: Result dictionary key expected to be empty or absent.
        error_code: Typed error code to emit when items are present.

    Raises:
        RecoveryStepFailedError: If the result list at key is non-empty.
    """
    value = step.result.get(key)
    if not isinstance(value, list) or not value:
        return
    details = ", ".join(str(item) for item in value)
    raise RecoveryStepFailedError(
        error_code=error_code,
        error_summary=f"{step.code} reported {key}: {details}",
    )
