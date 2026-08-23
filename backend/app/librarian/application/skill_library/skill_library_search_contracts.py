"""Contracts for search-first evaluation of reusable skill artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.librarian.domain.event_enum.skill_acquisition_enums import RiskLevel
from app.librarian.domain.event_enum.skill_search_enums import SkillSearchDecision
from app.shared.types.extra_types import JSONObject


@dataclass(slots=True, kw_only=True)
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
        self.required_tools = tuple(self.required_tools)
        self.constraints = tuple(self.constraints)
        self.success_criteria = tuple(self.success_criteria)


@dataclass(slots=True, kw_only=True)
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
        self.required_tools = tuple(self.required_tools)
        self.evidence = tuple(self.evidence)
        self.matched_terms = tuple(self.matched_terms)
        self.limitations = tuple(self.limitations)
        self.why_match = tuple(self.why_match)
        self.gaps = tuple(self.gaps)


@dataclass(slots=True, kw_only=True)
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
        self.candidates = tuple(self.candidates)
        self.gaps = tuple(self.gaps)
