"""Graph orphan census and deterministic relation suggestion read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

OrphanDecision = Literal["ACKNOWLEDGED_STANDALONE", "IGNORED_WITH_REASON"]
OrphanStatus = Literal[
    "OPEN",
    "RESOLVED",
    "ACKNOWLEDGED_STANDALONE",
    "IGNORED_WITH_REASON",
]


@dataclass(frozen=True, slots=True)
class ObsidianOrphanAcknowledgement:
    """Durable census acknowledgement for one degree-zero note."""

    note_id: str
    decision: OrphanDecision
    acknowledged_at: datetime
    acknowledged_by: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ObsidianGraphOrphanEntry:
    """One measured graph debt node with its census status."""

    note_id: str
    relative_path: str
    title: str
    project: str | None
    status: OrphanStatus
    in_degree: int | None
    out_degree: int | None
    canonical_parent_count: int | None
    has_wikilink_connectivity: bool | None
    debt_kinds: tuple[str, ...]
    has_declared_relations: bool | None
    acknowledgement_reason: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    first_seen_run_id: str | None = None
    last_seen_run_id: str | None = None
    graph_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class ObsidianGraphOrphanCensusResult:
    """One bounded, deterministically ordered orphan census page."""

    orphans: tuple[ObsidianGraphOrphanEntry, ...]
    total_orphans: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ObsidianGraphRelationSuggestion:
    """One evidence-backed, suggestion-only relation candidate."""

    candidate_note_id: str
    candidate_path: str
    candidate_title: str
    relation: str
    confidence: float
    shared_tags: tuple[str, ...]
    shared_neighbor_count: int
    title_overlap_tokens: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class ObsidianGraphRelationSuggestionsResult:
    """Deterministic relation suggestions for one seed note."""

    note_id: str
    relative_path: str
    suggestions: tuple[ObsidianGraphRelationSuggestion, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianOrphanCensusMetadata:
    """Durable bounded first/last-seen metadata for one graph debt record."""

    note_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    first_seen_run_id: str | None = None
    last_seen_run_id: str | None = None
    graph_run_id: str | None = None
