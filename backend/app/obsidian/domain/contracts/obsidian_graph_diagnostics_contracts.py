"""Typed contracts for Rust-owned graph orphan and suggestion diagnostics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphDiagnosticNote:
    """Typed note metadata supplied to the deterministic graph kernel."""

    note_id: str
    relative_path: str
    title: str
    project: str | None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphDiagnosticEdge:
    """Typed resolved graph edge supplied to the deterministic kernel."""

    edge_id: str
    source_note_id: str
    target_note_id: str | None
    relation: str
    source_kind: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphOrphanDiagnosticRequest:
    """Bounded stable orphan-page request."""

    project: str | None
    cursor: str | None
    limit: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphSuggestionDiagnosticRequest:
    """Bounded seed suggestion request."""

    seed_note_id: str
    limit: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphOrphanDiagnostic:
    """Rust-computed graph debt record."""

    note_id: str
    relative_path: str
    title: str
    project: str | None
    in_degree: int
    out_degree: int
    canonical_parent_count: int
    has_wikilink_connectivity: bool
    debt_kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphSuggestionDiagnostic:
    """Rust-computed relation suggestion evidence."""

    candidate_note_id: str
    candidate_path: str
    candidate_title: str
    relation: str
    confidence: float
    shared_tags: tuple[str, ...] = ()
    shared_neighbor_count: int = 0
    title_overlap_tokens: tuple[str, ...] = ()
    explanation: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphDiagnosticsResult:
    """Bounded deterministic graph diagnostics response."""

    contract_version: int
    graph_compute_version: int
    orphans: tuple[ObsidianGraphOrphanDiagnostic, ...] = ()
    total_orphans: int = 0
    next_cursor: str | None = None
    suggestions: tuple[ObsidianGraphSuggestionDiagnostic, ...] = ()
