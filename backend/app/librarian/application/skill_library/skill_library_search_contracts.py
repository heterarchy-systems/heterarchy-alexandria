"""Contracts for search-first evaluation of reusable skill artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.librarian.domain.event_enum.skill_search_enums import SkillSearchDecision
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSearchQuery
from app.obsidian.domain.entities.obsidian_note import ObsidianSearchHit
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillCapabilityBrief:
    """Normalized capability need used for skill-library search."""

    capability: str
    task_goal: str | None = None
    project: str | None = None
    environment: str | None = None
    required_tools: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    risk_tolerance: RiskLevel = RiskLevel.MEDIUM
    success_criteria: tuple[str, ...] = field(default_factory=tuple)
    limit: int = 5

    def __post_init__(self) -> None:
        """Normalize capability brief collections to immutable values."""
        object.__setattr__(self, "required_tools", tuple(self.required_tools))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "success_criteria", tuple(self.success_criteria))


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillSearchCandidate:
    """One normalized reusable skill candidate."""

    id: str
    path: str
    title: str
    status: str
    version: str | None
    project: str | None
    required_tools: tuple[str, ...]
    risk_level: RiskLevel
    evidence: tuple[str, ...]
    matched_terms: tuple[str, ...]
    limitations: tuple[str, ...]
    score: float
    sufficiency_score: int
    hard_gates: JSONObject
    why_match: tuple[str, ...]
    gaps: tuple[str, ...]
    recommended_action: str

    def __post_init__(self) -> None:
        """Normalize candidate evidence collections to immutable values."""
        object.__setattr__(self, "required_tools", tuple(self.required_tools))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "matched_terms", tuple(self.matched_terms))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "why_match", tuple(self.why_match))
        object.__setattr__(self, "gaps", tuple(self.gaps))


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillSearchResult:
    """Search-first result for one normalized capability brief."""

    decision: SkillSearchDecision
    query: str
    candidates: tuple[SkillSearchCandidate, ...]
    recommended_action: str
    gaps: tuple[str, ...]
    decision_explanation: JSONObject = field(default_factory=dict)
    handoff: JSONObject | None = None
    search_error: str | None = None

    def __post_init__(self) -> None:
        """Normalize search result collections to immutable values."""
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "gaps", tuple(self.gaps))


class SkillSearchBackend(Protocol):
    """Minimal Obsidian search capability required by the evaluator."""

    async def search(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = True,
    ) -> list[ObsidianSearchHit]:
        """Return matching Obsidian search hits.

        Args:
            query: Obsidian search query.
            refresh: Whether to refresh the index before searching.

        Returns:
            Ranked Obsidian search hits.
        """
