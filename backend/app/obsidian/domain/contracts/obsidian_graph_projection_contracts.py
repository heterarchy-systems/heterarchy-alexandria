"""Internal DTOs for the rebuildable Obsidian graph projection."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphContextSignalType,
    ObsidianGraphDirection,
    ObsidianGraphProjectionIssueCode,
    ObsidianGraphTraversalDirection,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionNode:
    """One Obsidian note projected into a graph read model."""

    note_id: str
    relative_path: str
    alexandria_type: AlexandriaNoteType
    title: str
    status: str
    project: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionEdge:
    """One stable relationship projected from Obsidian note metadata."""

    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str | None
    target_path: str
    relation: ObsidianRelationType
    confidence: float
    source_kind: ObsidianEdgeSourceKind


@dataclass(slots=True, kw_only=True)
class ObsidianGraphProjection:
    """Immutable node and edge snapshot for a graph projection."""

    nodes: tuple[ObsidianGraphProjectionNode, ...] = field(default_factory=tuple)
    edges: tuple[ObsidianGraphProjectionEdge, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize projection collections to immutable tuples."""
        self.nodes = tuple(self.nodes)
        self.edges = tuple(self.edges)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionIssueCount:
    """Count for one non-fatal source diagnostic code."""

    code: ObsidianGraphProjectionIssueCode
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionIssue:
    """One explicit source-index issue observed while building a projection."""

    code: ObsidianGraphProjectionIssueCode
    relative_path: str
    note_id: str | None = None
    edge_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionBatch:
    """One deterministic bounded write batch for a graph projection adapter."""

    batch_index: int
    projection: ObsidianGraphProjection


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphProjectionSourceMetrics:
    """Exact source-row dispositions used by rebuild reporting.

    ``indexed`` counts projected nodes and edges. ``skipped`` counts source
    rows that produced no projection item. Issues are diagnostics and are not
    added to either disposition a second time.
    """

    scanned: int
    indexed: int
    skipped: int
    errors: int


@dataclass(slots=True, kw_only=True)
class ObsidianGraphProjectionSourceSnapshot:
    """Typed projection snapshot plus bounded batches and source diagnostics."""

    projection: ObsidianGraphProjection
    batches: tuple[ObsidianGraphProjectionBatch, ...] = field(default_factory=tuple)
    issues: tuple[ObsidianGraphProjectionIssue, ...] = field(default_factory=tuple)
    metrics: ObsidianGraphProjectionSourceMetrics = field(
        default_factory=lambda: ObsidianGraphProjectionSourceMetrics(
            scanned=0,
            indexed=0,
            skipped=0,
            errors=0,
        )
    )

    def __post_init__(self) -> None:
        """Normalize source snapshot collections to immutable tuples."""
        self.batches = tuple(self.batches)
        self.issues = tuple(self.issues)


@dataclass(slots=True, kw_only=True)
class ObsidianGraphProjectionState:
    """Active projection plus safe application-owned run metadata."""

    initialized: bool
    run_id: str | None = None
    projection_version: int | None = None
    projection: ObsidianGraphProjection = field(default_factory=ObsidianGraphProjection)
    issue_total: int = 0
    issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """Normalize persisted diagnostic summaries to immutable tuples."""
        self.issue_counts = tuple(self.issue_counts)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphRelatedNote:
    """Typed one-hop relation returned by the graph read-model provider."""

    note_id: str
    edge_id: str
    relation: ObsidianRelationType
    source_kind: ObsidianEdgeSourceKind
    direction: ObsidianGraphDirection
    score: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphTraversalRequest:
    """One bounded traversal request over the already-active graph projection."""

    request_id: str
    start_note_id: str
    direction: ObsidianGraphTraversalDirection
    relations: tuple[str, ...]
    max_depth: int
    max_results: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphTraversalVisit:
    """One graph node discovered at a minimum stable hop distance."""

    note_id: str
    depth: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphTraversalResult:
    """Bounded deterministic traversal result for one requested seed note."""

    request_id: str
    start_note_id: str
    start_found: bool
    visits: tuple[ObsidianGraphTraversalVisit, ...]
    truncated: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphCandidatePathHop:
    """One Rust-owned shortest-path edge supporting a selected graph candidate."""

    edge_id: str
    source_note_id: str
    target_note_id: str
    relation: str
    direction: ObsidianGraphTraversalDirection
    depth: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphSelectedCandidate:
    """One relevance-bounded note selected from graph traversal evidence."""

    note_id: str
    min_depth: int
    seed_support: int
    shared_title_trigrams: int
    title_trigram_union: int
    path_hops: tuple[ObsidianGraphCandidatePathHop, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphTitleRelevance:
    """Query/title relevance evidence for one existing projected Context."""

    note_id: str
    shared_title_trigrams: int
    title_trigram_union: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphCandidateSelectionResult:
    """Deterministic traversal trace plus bounded selected graph candidates."""

    traversals: tuple[ObsidianGraphTraversalResult, ...]
    candidates: tuple[ObsidianGraphSelectedCandidate, ...]
    primary_title_relevance: tuple[ObsidianGraphTitleRelevance, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphContextEvidence:
    """One active-run graph edge whose endpoints are both recalled contexts."""

    signal: ObsidianGraphContextSignalType
    edge_id: str
    source_note_id: str
    target_note_id: str
    target_title: str
    relation: ObsidianRelationType
