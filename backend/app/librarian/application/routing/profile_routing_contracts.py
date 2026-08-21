"""Contracts returned by deterministic librarian profile routing."""

from __future__ import annotations

from dataclasses import dataclass

from app.librarian.domain.entities.read_models import AgentProfile


@dataclass(frozen=True, slots=True)
class LibrarianRoutingDecision:
    """Deterministic profile-routing result for one ask request."""

    selected_profiles: tuple[AgentProfile, ...]
    matched_specialties: tuple[str, ...]
    quality_review_added: bool
    reason: str
    max_librarian_agents: int | None


@dataclass(frozen=True, slots=True)
class ProfileScore:
    """Comparable profile score for deterministic routing."""

    profile: AgentProfile
    matched_specialties: tuple[str, ...]
    score: int
