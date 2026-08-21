"""Public payload mapping for Hermes librarian collaboration results."""

from __future__ import annotations

from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskResult,
    LibrarianDelegateResult,
)
from app.librarian.domain.types.hermes_collaboration_payload_types import (
    HermesLibrarianAskPayload,
    LibrarianDelegatePayload,
)


def ask_payload(result: HermesLibrarianAskResult) -> HermesLibrarianAskPayload:
    """Map one collaboration result to its public payload contract.

    Args:
        result: Domain collaboration result.

    Returns:
        Public Hermes collaboration payload.
    """
    delegates = [delegate_payload(delegate) for delegate in result.delegates]
    return HermesLibrarianAskPayload(
        job_id=result.job_id,
        status=result.status,
        decision=result.decision,
        librarian_available=result.librarian_available,
        self_acquisition_allowed=result.self_acquisition_allowed,
        recommendation=result.recommendation,
        provider_id=result.provider_id,
        candidate_id=result.candidate_id,
        librarian_profile_id=result.librarian_profile_id,
        librarian_model=result.librarian_model,
        librarian_role_prompt=result.librarian_role_prompt,
        max_librarian_agents=result.max_librarian_agents,
        route_preview=list(result.route_preview),
        selected_profiles=list(result.selected_profiles),
        matched_specialties=list(result.matched_specialties),
        quality_review_added=result.quality_review_added,
        routing_reason=result.routing_reason,
        delegates=delegates,
    )


def delegate_payload(result: LibrarianDelegateResult) -> LibrarianDelegatePayload:
    """Map one delegate result to its public payload contract.

    Args:
        result: Domain delegate execution result.

    Returns:
        Public delegate payload.
    """
    return LibrarianDelegatePayload(
        profile_id=result.profile_id,
        provider_id=result.provider_id,
        status=result.status,
        delegate_type=result.delegate_type,
        summary=result.summary,
        matched_specialties=list(result.matched_specialties),
    )
