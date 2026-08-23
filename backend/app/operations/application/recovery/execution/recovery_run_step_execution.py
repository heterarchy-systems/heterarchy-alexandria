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


async def _execute_or_skip_step(
    code: str,
    callback: StepCallable,
    parent_run: RecoveryRun | None,
    parent_success_steps: dict[tuple[str, str], RecoveryRunStepResult],
    input_payload: JSONObject | None = None,
) -> RecoveryRunStepResult:
    """Execute or skip step.

    Args:
        code: Code used by this operation.
        callback: Callback invoked by this operation.
        parent_run: Parent run used by this operation.
        parent_success_steps: Parent success steps used by this operation.
        input_payload: Input payload used by this operation.

    Returns:
        RecoveryRunStepResult result produced by execute or skip step.
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
    """Execute step.

    Args:
        code: Code used by this operation.
        callback: Callback invoked by this operation.
        input_payload: Input payload used by this operation.

    Returns:
        RecoveryRunStepResult result produced by execute step.
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
            code,
            status,
            1,
            started_at,
            finished_at,
            input_hash,
            result,
        )
    finished_at = datetime.now(UTC)
    return RecoveryRunStepResult(
        code,
        status,
        1,
        started_at,
        finished_at,
        input_hash,
        result,
    )


def _step_input_hash(
    code: str,
    input_payload: JSONObject | None,
) -> str:
    """Execute step input hash.

    Args:
        code: Code used by this operation.
        input_payload: Input payload used by this operation.

    Returns:
        str result produced by step input hash.
    """
    payload: JSONObject = {"code": code, "input": input_payload or {}}
    return sha256(dumps_pretty_json(payload)).hexdigest()


def _require_step_success(
    step: RecoveryRunStepResult,
    error_code: str,
) -> None:
    """Execute require step success.

    Args:
        step: Step used by this operation.
        error_code: Error code used by this operation.
    """
    if step.status in {RecoveryStepStatus.SUCCEEDED, RecoveryStepStatus.SKIPPED}:
        return
    raise RecoveryStepFailedError(
        error_code=error_code,
        error_summary=f"{step.code} failed",
    )


def _require_empty_result_list(
    step: RecoveryRunStepResult,
    key: str,
    error_code: str,
) -> None:
    """Execute require empty result list.

    Args:
        step: Step used by this operation.
        key: Key used by this operation.
        error_code: Error code used by this operation.
    """
    value = step.result.get(key)
    if not isinstance(value, list) or not value:
        return
    details = ", ".join(str(item) for item in value)
    raise RecoveryStepFailedError(
        error_code=error_code,
        error_summary=f"{step.code} reported {key}: {details}",
    )
