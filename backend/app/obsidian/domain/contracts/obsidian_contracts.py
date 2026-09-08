"""Application contracts for Obsidian vault operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianFrontmatterMode,
    ObsidianRelationType,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianChunkIndex:
    """Chunk data to store in the search cache."""

    chunk_index: int
    heading_path: str | None
    text: str
    content_hash: str
    token_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianEdgeIndex:
    """Graph edge discovered while indexing one Obsidian note."""

    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str | None
    target_path: str
    relation: ObsidianRelationType
    confidence: float
    source_kind: ObsidianEdgeSourceKind


@dataclass(slots=True, kw_only=True)
class ObsidianNoteIndex:
    """Normalized note data discovered during vault indexing."""

    note_id: str
    relative_path: str
    alexandria_type: AlexandriaNoteType
    title: str
    status: str
    tags: tuple[str, ...]
    project: str | None
    source: str | None
    content_hash: str
    frontmatter: JSONObject
    body: str
    size_bytes: int
    modified_at: datetime
    chunks: tuple[ObsidianChunkIndex, ...]
    edges: tuple[ObsidianEdgeIndex, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize indexed-note collections to immutable values."""
        self.tags = tuple(self.tags)
        self.chunks = tuple(self.chunks)
        self.edges = tuple(self.edges)


@dataclass(slots=True, kw_only=True)
class ObsidianSearchQuery:
    """Search parameters for Obsidian note retrieval."""

    query: str
    limit: int = 10
    alexandria_type: AlexandriaNoteType | None = None
    excluded_alexandria_types: tuple[AlexandriaNoteType, ...] = field(
        default_factory=tuple
    )
    project: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize search filters to immutable values."""
        self.excluded_alexandria_types = tuple(self.excluded_alexandria_types)
        self.tags = tuple(self.tags)


@dataclass(slots=True, kw_only=True)
class ObsidianSaveNote:
    """Payload for creating or replacing one managed Markdown note."""

    title: str
    body: str
    alexandria_type: AlexandriaNoteType
    note_id: str | None = None
    relative_path: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    status: str = "active"
    project: str | None = None
    source: str = "mcp"
    frontmatter: JSONObject = field(default_factory=dict)
    expected_content_hash: str | None = None

    def __post_init__(self) -> None:
        """Normalize note tags to an immutable sequence."""
        self.tags = tuple(self.tags)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianWriteNote:
    """Explicit create, update, or upsert command for one canonical note."""

    note: ObsidianSaveNote
    write_mode: ObsidianWriteMode
    match_by: ObsidianWriteMatchBy
    frontmatter_mode: ObsidianFrontmatterMode = ObsidianFrontmatterMode.MERGE
    provided_fields: frozenset[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianReportBundleOwner:
    """Existing note that should own one incoming relation to a report source."""

    path: str
    relation: ObsidianRelationType = ObsidianRelationType.CONTAINS


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianReportBundleVerify:
    """Verification stages requested after a report bundle write."""

    index_status: bool = True
    incoming_edges: bool = True
    duplicates: bool = True


@dataclass(slots=True, kw_only=True)
class ObsidianReportBundleRequest:
    """Idempotent Source/owner/reindex/graph verification operation."""

    idempotency_key: str
    source: ObsidianSaveNote
    graph_owners: tuple[ObsidianReportBundleOwner, ...]
    reindex: bool = True
    verify: ObsidianReportBundleVerify = field(
        default_factory=ObsidianReportBundleVerify
    )

    def __post_init__(self) -> None:
        """Normalize graph owner inputs to immutable values."""
        self.graph_owners = tuple(self.graph_owners)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianContextDuplicateQuery:
    """Canonical identity and content signature used for duplicate detection."""

    excluded_note_id: str
    scope: str
    project: str | None
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None
    content_hash: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultSettingsUpdate:
    """Payload for changing the runtime Obsidian vault destination."""

    vault_path: str
    alexandria_root: str = "."
    initialize: bool = True
    reindex: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultInventoryRequest:
    """Request to inventory managed notes under one vault scope."""

    scope_path: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultMoveRequest:
    """One explicit safe vault move request."""

    source_path: str
    destination_path: str
    reason: str


@dataclass(slots=True, kw_only=True)
class ObsidianVaultMovePlanRequest:
    """Dry-run safe move planning request."""

    moves: tuple[ObsidianVaultMoveRequest, ...]

    def __post_init__(self) -> None:
        """Normalize planned moves to an immutable sequence."""
        self.moves = tuple(self.moves)


@dataclass(slots=True, kw_only=True)
class ObsidianVaultMoveApplyRequest:
    """Safe move application request."""

    moves: tuple[ObsidianVaultMoveRequest, ...]
    report_path: str | None = None
    reindex: bool = True
    verification_query: str | None = None

    def __post_init__(self) -> None:
        """Normalize applied moves to an immutable sequence."""
        self.moves = tuple(self.moves)
