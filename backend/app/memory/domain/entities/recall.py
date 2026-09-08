"""Agent-facing recall results, provenance, and bounded search traces."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallProvenance:
    """Bounded evidence explaining why one Context match was returned."""

    route: RecallRoute
    project_affinity: RecallProjectAffinity
    canonical_context_id: str
    authority: str
    chunk_id: str
    heading: str | None
    project: str | None
    fts_score: float | None
    vector_score: float | None
    graph_score: float | None
    confidence: float
    exact_contribution: str | None
    source_revision: str | None
    index_revision: str | None
    lifecycle_eligible: bool
    temporal_eligible: bool | None
    title_alias_contribution: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallMatch:
    """One existing Context search match paired with high-level provenance."""

    match: ContextSearchMatch
    provenance: RecallProvenance


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallStageTrace:
    """Bounded evidence for one cascade stage."""

    route: RecallRoute
    status: RecallStageStatus
    hit_count: int
    project: str | None
    effective_strategy: RagStrategy | None
    reason: str | None
    warnings: tuple[str, ...] = ()
    degraded: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallTrace:
    """Compact route, fallback, and confidence trace for one recall."""

    stages: tuple[RecallStageTrace, ...]
    skipped_scopes: tuple[str, ...]
    fallback_expansion: tuple[RecallRoute, ...]
    degraded_subsystems: tuple[str, ...]
    outcome: RecallOutcome
    confidence: float
    search_call_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RecallResult:
    """High-level recall response independent of HTTP or MCP transport."""

    query: str
    scope_mode: RecallScopeMode
    recall_scopes: tuple[ContextScope, ...]
    effective_strategy: RagStrategy
    outcome: RecallOutcome
    warnings: tuple[str, ...]
    matches: tuple[RecallMatch, ...]
    context_pack: str
    trace: RecallTrace
