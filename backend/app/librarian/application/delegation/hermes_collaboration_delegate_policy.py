"""Delegate execution decision policy for Hermes librarian collaboration."""

from __future__ import annotations

from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianDelegateExecutor,
    LibrarianExecutionPlan,
)
from app.librarian.application.delegation.delegate_execution_runner import (
    execute_delegates,
)
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.event_enum.collaboration_enums import (
    AcquisitionDecision,
    LibrarianDelegateStatus,
    LibrarianDelegationStatus,
)

_SELF_RESEARCH_RECOMMENDATION = (
    "적절한 skill이 없다면 Hermes가 먼저 공식 문서나 웹 근거를 조사해 "
    "skill candidate를 제출할 수 있습니다. 바쁘면 사서에게 위임하세요."
)
_DELEGATION_COMPLETED_MESSAGE = (
    "사서 delegate가 완료되었습니다. delegates 응답에서 profile별 결과와 "
    "matched_specialties를 확인하세요."
)
_DELEGATION_SKIPPED_MESSAGE = (
    "사서 delegate를 완료하지 못했습니다. delegates 응답의 SKIPPED 항목과 "
    "summary를 확인하고 Hermes 직접 조사 또는 인증/제공자 설정을 점검하세요."
)


async def delegate_decision(
    should_delegate: bool,
    executable_plans: list[LibrarianExecutionPlan],
    max_librarian_agents: int | None,
    command: HermesLibrarianAskCommand,
    executor: LibrarianDelegateExecutor | None,
) -> tuple[
    list[LibrarianDelegateResult],
    LibrarianDelegationStatus,
    AcquisitionDecision,
    str,
]:
    """Execute eligible delegates and classify the collaboration outcome.

    Args:
        should_delegate: Whether the request selected delegated execution.
        executable_plans: Provider-backed execution plans.
        max_librarian_agents: Maximum concurrent librarian delegates.
        command: Original Hermes collaboration command.
        executor: Optional provider-backed delegate executor.

    Returns:
        Delegate results, top-level status, decision, and recommendation.
    """
    delegates: list[LibrarianDelegateResult] = []
    status = LibrarianDelegationStatus.GUIDANCE_ONLY
    decision = AcquisitionDecision.SUGGEST_HERMES_RESEARCH
    recommendation = _SELF_RESEARCH_RECOMMENDATION
    if should_delegate:
        delegates = await execute_delegates(
            executable_plans,
            max_librarian_agents,
            command=command,
            executor=executor,
        )
        if completed_delegate_count(delegates) > 0:
            status = LibrarianDelegationStatus.COMPLETED
            decision = AcquisitionDecision.DELEGATE_TO_LIBRARIAN
            recommendation = _DELEGATION_COMPLETED_MESSAGE
        elif delegates:
            recommendation = _DELEGATION_SKIPPED_MESSAGE
    return delegates, status, decision, recommendation


def completed_delegate_count(delegates: list[LibrarianDelegateResult]) -> int:
    """Count delegates that completed provider-backed execution.

    Args:
        delegates: Delegate execution results.

    Returns:
        Number of completed delegates.
    """
    return sum(
        1
        for delegate in delegates
        if delegate.status is LibrarianDelegateStatus.COMPLETED
    )
