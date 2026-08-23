"""Internal contracts for Hermes librarian collaboration flows."""

from __future__ import annotations

from dataclasses import dataclass

from app.librarian.domain.entities.source_ref import SourceRef
from app.librarian.domain.event_enum.collaboration_enums import (
    AcquisitionDecision,
    LibrarianDelegateKind,
    LibrarianDelegateStatus,
    LibrarianDelegationStatus,
)


@dataclass(slots=True, kw_only=True)
class HermesLibrarianAskCommand:
    """Command produced when Hermes asks the librarian for work guidance."""

    prompt: str
    agent_name: str
    project: str | None
    task_summary: str | None
    delegate_to_librarian: bool
    provider_id: str | None
    librarian_profile_id: str | None
    librarian_model: str | None
    librarian_role_prompt: str | None
    max_librarian_agents: int | None
    routing_specialties: tuple[str, ...]
    source_refs: tuple[SourceRef, ...] = ()
    librarian_brief: str | None = None

    def __post_init__(self) -> None:
        """Normalize routing specialties to an immutable sequence."""
        self.routing_specialties = tuple(self.routing_specialties)


@dataclass(slots=True, kw_only=True)
class LibrarianDelegateResult:
    """Result from one synchronous librarian delegate lane."""

    profile_id: str
    provider_id: str | None
    status: LibrarianDelegateStatus
    delegate_type: LibrarianDelegateKind
    summary: str
    matched_specialties: tuple[str, ...]

    def __post_init__(self) -> None:
        """Normalize delegate specialty matches to an immutable sequence."""
        self.matched_specialties = tuple(self.matched_specialties)


@dataclass(slots=True, kw_only=True)
class HermesLibrarianAskResult:
    """Result returned to Hermes after an ask/delegation request."""

    job_id: str
    status: LibrarianDelegationStatus
    decision: AcquisitionDecision
    librarian_available: bool
    self_acquisition_allowed: bool
    recommendation: str
    provider_id: str | None
    candidate_id: str | None
    librarian_profile_id: str | None
    librarian_model: str | None
    librarian_role_prompt: str | None
    max_librarian_agents: int | None
    route_preview: tuple[str, ...]
    selected_profiles: tuple[str, ...]
    matched_specialties: tuple[str, ...]
    quality_review_added: bool
    routing_reason: str
    delegates: tuple[LibrarianDelegateResult, ...]

    def __post_init__(self) -> None:
        """Normalize collaboration route and delegate collections."""
        self.route_preview = tuple(self.route_preview)
        self.selected_profiles = tuple(self.selected_profiles)
        self.matched_specialties = tuple(self.matched_specialties)
        self.delegates = tuple(self.delegates)
