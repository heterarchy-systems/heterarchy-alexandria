"""Context Vault read models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
    ContextContentFormat,
    ContextGraphDirection,
    ContextGraphSignalType,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    MemoryFunction,
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.types.extra_types import JSONObject


@dataclass(slots=True)
class ContextRecord:
    """Read model for one stored context."""

    id: str
    kind: ContextKind
    title: str
    summary: str
    content: str
    content_format: ContextContentFormat
    project: str | None
    scope: ContextScope
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None
    visibility: ContextScope
    source_agent: str
    source_type: ContextSourceType
    importance: ContextImportance
    tags: tuple[str, ...]
    status: ContextStorageStatus
    quality_score: int
    warnings: tuple[str, ...]
    restore_prompt: str | None
    context_metadata: ContextMetadataPayload
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    expires_at: datetime | None
    archived_at: datetime | None
    access_count: int
    is_archived: bool
    memory_function: MemoryFunction | None = None

    def __post_init__(self) -> None:
        """Normalize mutable collection inputs to immutable read-model values."""
        self.tags = tuple(self.tags)
        self.warnings = tuple(self.warnings)


@dataclass(frozen=True, slots=True)
class ContextChunkRecord:
    """Read model for one context chunk."""

    id: str
    context_id: str
    chunk_index: int
    heading: str | None
    content: str
    token_count: int
    content_hash: str
    chunk_metadata: ContextMetadataPayload
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ContextAccessEventRecord:
    """Read model for one Context Vault access event."""

    id: str
    context_id: str
    accessed_at: datetime
    actor_name: str
    actor_type: ContextAccessActorType
    access_method: ContextAccessMethod
    source_surface: str | None


@dataclass(frozen=True, slots=True)
class ContextGraphEvidence:
    """One optional graph relationship explaining a recalled Context."""

    signal: ContextGraphSignalType
    relation: str
    direction: ContextGraphDirection
    source_context_id: str
    target_context_id: str
    target_title: str
    distance: int
    evidence_ref: str


@dataclass(slots=True)
class ContextSearchMatch:
    """One retrieved chunk with its parent context."""

    context: ContextRecord
    chunk: ContextChunkRecord
    score: float
    fts_score: float | None
    vector_score: float | None
    why_retrieved: str
    graph_score: float | None = None
    graph_evidence: tuple[ContextGraphEvidence, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize graph evidence to an immutable tuple."""
        self.graph_evidence = tuple(self.graph_evidence)


@dataclass(slots=True)
class RagDependencyHealth:
    """Health state for context RAG dependencies."""

    fts: RagHealthState
    vector: RagHealthState
    embedding: RagHealthState
    default_strategy: RagStrategy
    model_name: str
    dimensions: int
    fingerprint: JSONObject | None
    warnings: tuple[str, ...]
    source_statuses: tuple[ContextEmbeddingSourceStatus, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """Normalize health collections to immutable values."""
        self.warnings = tuple(self.warnings)
        self.source_statuses = tuple(self.source_statuses)


@dataclass(slots=True)
class ContextEmbeddingSourceStatus:
    """Embedding fingerprint status for one configured retrieval source."""

    source_name: str
    status: RagHealthState
    total_rows: int
    current_rows: int
    stale_rows: int
    missing_rows: int
    current_fingerprint: JSONObject
    stored_fingerprints: tuple[JSONObject, ...]

    def __post_init__(self) -> None:
        """Normalize stored fingerprint rows to an immutable sequence."""
        self.stored_fingerprints = tuple(self.stored_fingerprints)


@dataclass(slots=True)
class ContextReindexResult:
    """Result for a context embedding reindex operation."""

    scanned: int
    updated: int
    skipped: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        """Normalize reindex warnings to an immutable sequence."""
        self.warnings = tuple(self.warnings)


@dataclass(slots=True)
class ContextSoftRebuildResult:
    """Operator-facing result for a soft embedding/vector rebuild."""

    mode: str
    source_preservation: str
    hard_delete_performed: bool
    before: RagDependencyHealth
    source_status_before: tuple[ContextEmbeddingSourceStatus, ...]
    reindex: ContextReindexResult
    after: RagDependencyHealth
    source_status_after: tuple[ContextEmbeddingSourceStatus, ...]
    verification_query: str | None
    verification_matches: int
    verification_context_ids: tuple[str, ...]
    verification_warnings: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        """Normalize soft-rebuild report collections to immutable values."""
        self.source_status_before = tuple(self.source_status_before)
        self.source_status_after = tuple(self.source_status_after)
        self.verification_context_ids = tuple(self.verification_context_ids)
        self.verification_warnings = tuple(self.verification_warnings)
        self.warnings = tuple(self.warnings)


@dataclass(slots=True)
class ContextPack:
    """Agent-facing RAG context pack."""

    query: str
    strategy: RagStrategy
    effective_strategy: RagStrategy
    warnings: tuple[str, ...]
    recall_scopes: tuple[ContextScope, ...]
    matches: tuple[ContextSearchMatch, ...]
    context_pack: str

    def __post_init__(self) -> None:
        """Normalize context-pack collections to immutable values."""
        self.warnings = tuple(self.warnings)
        self.recall_scopes = tuple(self.recall_scopes)
        self.matches = tuple(self.matches)
