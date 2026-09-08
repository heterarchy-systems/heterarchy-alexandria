"""Read models for Obsidian-backed Alexandria notes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianIndexErrorCode,
    ObsidianIndexStatus,
    ObsidianRelationType,
    ObsidianReportBundleCompletionStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianChunk:
    """Searchable chunk for one Obsidian note."""

    id: str
    note_id: str
    chunk_index: int
    heading_path: str | None
    text: str
    content_hash: str
    token_count: int


@dataclass(slots=True, kw_only=True)
class ObsidianNote:
    """Indexed Alexandria-managed Markdown note."""

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
    index_status: ObsidianIndexStatus
    error_message: str | None
    size_bytes: int
    modified_at: datetime
    indexed_at: datetime | None

    def __post_init__(self) -> None:
        """Normalize note tags to an immutable sequence."""
        self.tags = tuple(self.tags)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultSourceSnapshot:
    """Bounded source-owned Markdown snapshot for exact identity resolution."""

    notes: tuple[ObsidianNoteIndex, ...]
    complete: bool
    scanned_paths: int
    errors: tuple[str, ...] = field(default_factory=tuple)
    entries_seen: int = 0
    total_bytes: int = 0

    def __post_init__(self) -> None:
        """Normalize snapshot collections to immutable sequences."""
        object.__setattr__(self, "notes", tuple(self.notes))
        object.__setattr__(self, "errors", tuple(self.errors))


@dataclass(slots=True, kw_only=True)
class ObsidianNoteWriteResult:
    """Structured outcome and pipeline visibility for an explicit note write."""

    operation: ObsidianWriteOperation
    write_mode: ObsidianWriteMode
    match_by: ObsidianWriteMatchBy
    note: ObsidianNote
    storage_status: str
    metadata_status: str
    fts_status: str
    graph_edge_index_status: str
    graph_projection_status: str
    reindex_required: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize warnings to an immutable sequence."""
        self.warnings = tuple(self.warnings)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianExactPathStatus:
    """Existence and identity result for one canonical managed path."""

    exists: bool
    relative_path: str
    note_id: str | None = None
    index_status: ObsidianIndexStatus | None = None


@dataclass(slots=True, kw_only=True)
class ObsidianCanonicalIdentityResult:
    """Generic frontmatter-backed canonical report identity resolution."""

    canonical_report_family: str
    canonical_entity: str
    canonical_path: str
    existing_note_id: str | None
    aliases: tuple[str, ...]
    resolution: str
    candidate_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize resolver collections to immutable sequences."""
        self.aliases = tuple(self.aliases)
        self.candidate_paths = tuple(self.candidate_paths)


@dataclass(slots=True, kw_only=True)
class ObsidianReportBundleGraphResult:
    """Expected and observed graph state for one report bundle."""

    expected_incoming_edges: int
    verified_incoming_edges: int
    unresolved_links: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize unresolved links to an immutable sequence."""
        self.unresolved_links = tuple(self.unresolved_links)


@dataclass(slots=True, kw_only=True)
class ObsidianReportBundleResult:
    """Checkpointable outcome for an idempotent report bundle operation."""

    completion_status: ObsidianReportBundleCompletionStatus
    idempotency_key: str
    replayed: bool
    source: ObsidianNoteWriteResult | None
    owner_writes: tuple[ObsidianNoteWriteResult, ...]
    graph: ObsidianReportBundleGraphResult
    duplicates: tuple[str, ...] = field(default_factory=tuple)
    failed_stage: str | None = None
    rollback_performed: bool = False
    errors: tuple[JSONObject, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize bundle collections to immutable values."""
        self.owner_writes = tuple(self.owner_writes)
        self.duplicates = tuple(self.duplicates)
        self.errors = tuple(self.errors)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianEdge:
    """Indexed graph edge between Obsidian notes."""

    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str | None
    target_path: str
    relation: ObsidianRelationType
    confidence: float
    source_kind: ObsidianEdgeSourceKind
    created_at: datetime
    indexed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianRelatedNote:
    """Related note result ranked by graph edge evidence."""

    note: ObsidianNote
    relation: ObsidianRelationType
    source_kind: ObsidianEdgeSourceKind
    direction: str
    score: float
    edge_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianSearchHit:
    """One Obsidian search result with path and snippet metadata."""

    note: ObsidianNote
    excerpt: str
    score: float
    chunk_id: str | None = None
    heading_path: str | None = None


@dataclass(slots=True, kw_only=True)
class ObsidianReindexResult:
    """Summary of one vault indexing pass."""

    files_seen: int
    files_indexed: int
    files_skipped: int
    stale_marked: int
    errors: tuple[str, ...] = field(default_factory=tuple)
    error_details: tuple[ObsidianIndexError, ...] = field(default_factory=tuple)
    skip_reasons: dict[str, int] = field(default_factory=dict)
    edge_targets_resolved: int = 0

    def __post_init__(self) -> None:
        """Normalize reindex diagnostics to immutable sequences."""
        self.errors = tuple(self.errors)
        self.error_details = tuple(self.error_details)
        self.skip_reasons = dict(self.skip_reasons)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianIndexError:
    """Structured failure recorded for one note during reindex."""

    note_path: str
    context_id: str | None
    error_code: ObsidianIndexErrorCode
    error_message: str
    detected_at: datetime


@dataclass(slots=True, kw_only=True)
class ObsidianVaultStatus:
    """Local Obsidian integration status."""

    vault_path: str
    alexandria_root: str
    vault_exists: bool
    alexandria_root_exists: bool
    indexed_notes: int
    stale_notes: int
    error_notes: int
    index_errors: tuple[ObsidianIndexError, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize index errors to an immutable sequence."""
        self.index_errors = tuple(self.index_errors)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultLocation:
    """Canonical Vault location without opening the rebuildable index."""

    vault_path: str
    alexandria_root: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultInventoryItem:
    """One managed Markdown note discovered by vault inventory."""

    note_id: str
    relative_path: str
    alexandria_type: AlexandriaNoteType
    title: str
    status: str
    tags: tuple[str, ...]
    project: str | None
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultMoveCandidate:
    """One planned vault move after safety validation."""

    source_path: str
    destination_path: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultMoveSkip:
    """One skipped vault move with the safety reason."""

    source_path: str
    destination_path: str
    reason: str


@dataclass(slots=True, kw_only=True)
class ObsidianVaultMovePlan:
    """Dry-run plan for a safe vault move operation."""

    status: str
    hard_delete_performed: bool
    moves: tuple[ObsidianVaultMoveCandidate, ...]
    skipped: tuple[ObsidianVaultMoveSkip, ...]
    ambiguous: tuple[ObsidianVaultMoveSkip, ...]

    def __post_init__(self) -> None:
        """Normalize planned move groups to immutable sequences."""
        self.moves = tuple(self.moves)
        self.skipped = tuple(self.skipped)
        self.ambiguous = tuple(self.ambiguous)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultMoveApplied:
    """One move that was safely applied."""

    source_path: str
    destination_path: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianVaultMoveVerification:
    """Verification summary after applying a vault move plan."""

    source_root_loose_notes_remaining: int
    reindex_status: str
    verification_hits: int


@dataclass(slots=True, kw_only=True)
class ObsidianVaultMoveReport:
    """Final report for a safe vault move operation."""

    status: str
    hard_delete_performed: bool
    moved: tuple[ObsidianVaultMoveApplied, ...]
    skipped: tuple[ObsidianVaultMoveSkip, ...]
    ambiguous: tuple[ObsidianVaultMoveSkip, ...]
    verification: ObsidianVaultMoveVerification
    report_markdown_path: str
    report_json_path: str

    def __post_init__(self) -> None:
        """Normalize applied move groups to immutable sequences."""
        self.moved = tuple(self.moved)
        self.skipped = tuple(self.skipped)
        self.ambiguous = tuple(self.ambiguous)
