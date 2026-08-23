"""Context Vault payload contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NotRequired

from typing_extensions import TypedDict

from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
    ContextContentFormat,
    ContextGraphDirection,
    ContextGraphSignalType,
    ContextImportance,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagHealthState,
    RagStrategy,
)
from app.shared.types.extra_types import JSONObject, JSONValue

type ContextRetrievalSource = Literal["context_vault", "obsidian_vault"]


class ContextMetadataPayload(TypedDict, extra_items=JSONValue):
    """Known Context metadata fields plus preserved caller extensions."""

    source_surface: NotRequired[str]
    obsidian_note_id: NotRequired[str]
    canonical_context_id: NotRequired[str]
    relative_path: NotRequired[str]
    alexandria_type: NotRequired[str]
    index_status: NotRequired[str]
    wikilink: NotRequired[str]
    lifecycle_status: NotRequired[str]
    content_hash: NotRequired[str]
    version: NotRequired[int]
    provenance: NotRequired[dict[str, JSONValue]]
    supersedes_context_id: NotRequired[str | None]
    superseded_by_context_id: NotRequired[str | None]
    source: NotRequired[str]


class ContextProvenancePayload(TypedDict, closed=True):
    """Generalized origin and evidence references for one Context."""

    source_actor_id: str | None
    source_actor_type: ContextSourceType | None
    source_run_id: str | None
    external_run_id: str | None
    artifact_refs: list[str]
    evidence_refs: list[str]
    confidence: ContextImportance | None


class ContextLifecyclePayload(TypedDict, closed=True):
    """Canonical lifecycle and integrity metadata for one Context."""

    status: ContextRecallLifecycleStatus
    content_hash: str | None
    version: int | None
    supersedes_context_id: str | None
    superseded_by_context_id: str | None


class ContextLintNormalizedPayload(TypedDict, closed=True):
    """Normalized lint fields after boundary validation."""

    kind: ContextKind
    title: str
    summary: str
    project: str | None
    scope: ContextScope
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None
    visibility: ContextScope
    source_agent: str
    tags: list[str]


class SaveSuggestionPayload(TypedDict, closed=True):
    """Agent-facing signal for whether content should become durable memory."""

    should_save: bool
    suggested_kind: ContextKind
    suggested_scope: ContextScope
    reason: str


class ContextPayload(TypedDict, closed=True):
    """API payload for one stored context."""

    id: str
    canonical_context_id: str
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
    tags: list[str]
    status: ContextStorageStatus
    lifecycle_status: ContextRecallLifecycleStatus
    provenance: ContextProvenancePayload
    lifecycle: ContextLifecyclePayload
    quality_score: int
    warnings: list[str]
    restore_prompt: str | None
    metadata: ContextMetadataPayload
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    expires_at: datetime | None
    archived_at: datetime | None
    access_count: int
    is_archived: bool


class ContextChunkPayload(TypedDict, closed=True):
    """API payload for one stored context chunk."""

    id: str
    context_id: str
    chunk_index: int
    heading: str | None
    content: str
    token_count: int
    content_hash: str
    metadata: ContextMetadataPayload
    created_at: datetime


class ContextAccessEventPayload(TypedDict, closed=True):
    """API payload for one context access event."""

    id: str
    context_id: str
    accessed_at: datetime
    actor_name: str
    actor_type: ContextAccessActorType
    access_method: ContextAccessMethod
    source_surface: str | None


class ContextGraphEvidencePayload(TypedDict, closed=True):
    """API payload for one graph relationship explaining recall."""

    signal: ContextGraphSignalType
    relation: str
    direction: ContextGraphDirection
    source_context_id: str
    target_context_id: str
    target_title: str
    distance: int
    evidence_ref: str


class ContextSearchMatchPayload(TypedDict, closed=True):
    """API payload for one retrieved context match."""

    context: ContextPayload
    chunk: ContextChunkPayload
    score: float
    fts_score: float | None
    vector_score: float | None
    why_retrieved: str
    canonical_context_id: str
    lifecycle_status: ContextRecallLifecycleStatus
    source: ContextRetrievalSource
    retrieval_strategy: RagStrategy
    graph_evidence: list[ContextGraphEvidencePayload] | None


class ContextPackPayload(TypedDict, closed=True):
    """API payload for one RAG Context Pack."""

    query: str
    strategy: RagStrategy
    effective_strategy: RagStrategy
    warnings: list[str]
    recall_scopes: list[ContextScope]
    matches: list[ContextSearchMatchPayload]
    context_pack: str


class ContextEmbeddingSourceStatusPayload(TypedDict, closed=True):
    """API payload for source-level embedding fingerprint diagnostics."""

    source_name: str
    status: RagHealthState
    total_rows: int
    current_rows: int
    stale_rows: int
    missing_rows: int
    current_fingerprint: JSONObject
    stored_fingerprints: list[JSONObject]


class RagHealthPayload(TypedDict, closed=True):
    """API payload for RAG dependency health."""

    fts: RagHealthState
    vector: RagHealthState
    embedding: RagHealthState
    default_strategy: RagStrategy
    model_name: str
    dimensions: int
    fingerprint: JSONObject | None
    warnings: list[str]
    source_statuses: list[ContextEmbeddingSourceStatusPayload]


class ContextReindexPayload(TypedDict, closed=True):
    """API payload for context embedding reindex results."""

    scanned: int
    updated: int
    skipped: int
    warnings: list[str]


class ContextSoftRebuildPayload(TypedDict, closed=True):
    """API payload for context embedding soft rebuild results."""

    mode: str
    source_preservation: str
    hard_delete_performed: bool
    before: RagHealthPayload
    source_status_before: list[ContextEmbeddingSourceStatusPayload]
    reindex: ContextReindexPayload
    after: RagHealthPayload
    source_status_after: list[ContextEmbeddingSourceStatusPayload]
    verification_query: str | None
    verification_matches: int
    verification_context_ids: list[str]
    verification_warnings: list[str]
    warnings: list[str]
