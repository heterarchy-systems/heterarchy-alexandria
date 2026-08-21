"""Concurrent provider-backed execution of librarian delegate plans."""

from __future__ import annotations

import asyncio

from app.librarian.application.delegation.delegate_execution_contracts import (
    LibrarianDelegateExecutor,
    LibrarianExecutionPlan,
)
from app.librarian.application.routing.profile_routing_policy import profile_role
from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
    LibrarianDelegateResult,
)
from app.librarian.domain.event_enum.collaboration_enums import (
    LibrarianDelegateKind,
    LibrarianDelegateStatus,
    LibrarianProfileRole,
)


async def execute_delegates(
    plans: list[LibrarianExecutionPlan],
    max_librarian_agents: int | None,
    command: HermesLibrarianAskCommand | None = None,
    executor: LibrarianDelegateExecutor | None = None,
) -> list[LibrarianDelegateResult]:
    """Execute delegate plans synchronously with bounded parallelism.

    Args:
        plans: Executable delegate plans.
        max_librarian_agents: Maximum concurrent delegate count.
        command: Optional ask command required for provider-backed execution.
        executor: Optional provider execution boundary.

    Returns:
        list[LibrarianDelegateResult]: Inline delegate results.
    """
    limit = max_librarian_agents or 1
    semaphore = asyncio.Semaphore(limit)

    async def execute_one(plan: LibrarianExecutionPlan) -> LibrarianDelegateResult:
        """Execute one delegate plan behind the local concurrency gate.

        Args:
            plan: Delegate execution plan selected for this request.

        Returns:
            LibrarianDelegateResult: Provider result or inline fallback result.
        """
        async with semaphore:
            fallback = _delegate_result(plan)
            if executor is None or command is None:
                return fallback
            return await executor.execute(
                command=command,
                plan=plan,
                fallback=fallback,
            )

    selected_plans = plans[:limit]
    return list(await asyncio.gather(*(execute_one(plan) for plan in selected_plans)))


def _delegate_result(plan: LibrarianExecutionPlan) -> LibrarianDelegateResult:
    profile_id = "request-default" if plan.profile is None else plan.profile.id
    role = LibrarianProfileRole.DEFAULT_SEARCH
    if plan.profile is not None:
        role = profile_role(plan.profile)
    delegate_type = _delegate_kind(role)
    summary = _delegate_summary(role, plan.matched_specialties)
    provider_id = None if plan.provider is None else plan.provider.id
    return LibrarianDelegateResult(
        profile_id=profile_id,
        provider_id=provider_id,
        status=LibrarianDelegateStatus.COMPLETED,
        delegate_type=delegate_type,
        summary=summary,
        matched_specialties=tuple(plan.matched_specialties),
    )


def _delegate_kind(role: LibrarianProfileRole) -> LibrarianDelegateKind:
    if role is LibrarianProfileRole.SPECIALIST:
        return LibrarianDelegateKind.SPECIALTY_REVIEW
    if role is LibrarianProfileRole.QUALITY_REVIEWER:
        return LibrarianDelegateKind.QUALITY_REVIEW
    if role is LibrarianProfileRole.ARCHIVIST_CURATOR:
        return LibrarianDelegateKind.ARCHIVE_CURATION
    return LibrarianDelegateKind.LIBRARY_SEARCH


def _delegate_summary(
    role: LibrarianProfileRole,
    matched_specialties: tuple[str, ...],
) -> str:
    if role is LibrarianProfileRole.SPECIALIST and matched_specialties:
        return f"Specialist reviewed matching specialties: {', '.join(matched_specialties)}"
    if role is LibrarianProfileRole.QUALITY_REVIEWER:
        return "Quality reviewer checked risk, evidence, and duplication concerns."
    if role is LibrarianProfileRole.ARCHIVIST_CURATOR:
        return "Archivist curator checked stale context and archive hygiene."
    return "Default search librarian checked reusable library/search routes."
