"""Map Obsidian index rows into Context RAG read models."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.application.integration.obsidian_context_read_mapper import (
    OBSIDIAN_CONTEXT_ID_PREFIX,
    context_record_from_obsidian_note,
)
from app.memory.application.retrieval.planning.context_scope_filter import (
    context_matches_scope,
)
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_index_mapping import (
    note_from_model,
)
from app.shared.types.types_convert_utils import aware_utc_datetime

OBSIDIAN_CHUNK_ID_PREFIX = "obsidian-chunk:"
DEFAULT_EXCLUDED_OBSIDIAN_RECALL_TYPES = frozenset()
DEFAULT_EXCLUDED_OBSIDIAN_RECALL_PREFIXES = ("_Ops/",)


def matches_context_filters(
    note: ObsidianFileORM,
    context: ContextRecord,
    kind: ContextKind | None,
    scope_filter: ScopeIdentity | None,
    project: str | None = None,
    include_lifecycle_statuses: Sequence[ContextRecallLifecycleStatus] | None = None,
) -> bool:
    """Return whether an Obsidian context matches the requested filters.

    Args:
        note: Obsidian note or note record being mapped or evaluated.
        context: Context metadata associated with the note or chunk.
        kind: Context kind required by the filter.
        scope_filter: Optional context scope required by the filter.
        project: Project scope associated with the artifact or context.
        include_lifecycle_statuses: Lifecycle statuses allowed by the context filter.

    Returns:
        True when the requested filters match; otherwise False.
    """
    if not is_recall_visible(note, include_lifecycle_statuses):
        return False
    if kind is not None and context.kind != kind:
        return False
    if scope_filter is not None:
        return context_matches_scope(context, scope_filter)
    return project is None or context.project == project


def is_default_recall_visible(note: ObsidianFileORM) -> bool:
    """Return whether a note belongs in default agent recall.

    Args:
        note: Indexed Obsidian note row.

    Returns:
        True when the note is safe for default Context RAG recall.
    """
    return is_recall_visible(note, None)


def is_recall_visible(
    note: ObsidianFileORM,
    include_lifecycle_statuses: Sequence[ContextRecallLifecycleStatus] | None,
) -> bool:
    """Return whether a note is safe and lifecycle-eligible for recall.

    Args:
        note: Indexed Obsidian note row.
        include_lifecycle_statuses: Optional administrative lifecycle filter.

    Returns:
        True when index, type, path, and lifecycle checks all allow recall.
    """
    if note.index_status != ObsidianIndexStatus.INDEXED.value:
        return False
    if note.alexandria_type in DEFAULT_EXCLUDED_OBSIDIAN_RECALL_TYPES:
        return False
    normalized_status = note.status.strip().lower() or "active"
    allowed_statuses = ContextRecallLifecycleStatus.obsidian_values(
        include_lifecycle_statuses
    )
    if normalized_status not in allowed_statuses:
        return False
    return not note.relative_path.startswith(DEFAULT_EXCLUDED_OBSIDIAN_RECALL_PREFIXES)


def match_from_obsidian_rows(
    note: ObsidianFileORM,
    chunk: ObsidianChunkORM,
    context: ContextRecord,
    score: float,
    fts_score: float | None,
    vector_score: float | None,
    why_retrieved: str,
) -> ContextSearchMatch:
    """Build a context match from Obsidian rows.

    Args:
        note: Obsidian note or note record being mapped or evaluated.
        chunk: Obsidian or context chunk being mapped.
        context: Context metadata associated with the note or chunk.
        score: Combined retrieval score assigned to the match.
        fts_score: Full-text-search score contributing to the combined match.
        vector_score: Vector similarity score contributing to the combined match.
        why_retrieved: Human-readable retrieval rationale attached to the match.

    Returns:
        Context search match assembled from rows, scores, and retrieval rationale.
    """
    chunk_record = chunk_record_from_obsidian_row(chunk, title=note.title)
    return ContextSearchMatch(
        context=context,
        chunk=chunk_record,
        score=score,
        fts_score=fts_score,
        vector_score=vector_score,
        why_retrieved=why_retrieved,
    )


def context_record_from_obsidian_row(note: ObsidianFileORM) -> ContextRecord:
    """Build a context record from an Obsidian row.

    Args:
        note: Obsidian note or note record being mapped or evaluated.

    Returns:
        Context record mapped from the Obsidian note row.
    """
    return context_record_from_obsidian_note(note_from_model(note))


def chunk_record_from_obsidian_row(
    chunk: ObsidianChunkORM,
    title: str,
) -> ContextChunkRecord:
    """Build a chunk record from an Obsidian row.

    Args:
        chunk: Obsidian or context chunk being mapped.
        title: Human-readable title for the note or artifact.

    Returns:
        Context chunk record mapped from the Obsidian chunk row.
    """
    metadata = ContextMetadataPayload(
        source_surface="obsidian_vault",
        obsidian_note_id=chunk.note_id,
        title=title,
        heading=chunk.heading_path,
    )
    return ContextChunkRecord(
        id=f"{OBSIDIAN_CHUNK_ID_PREFIX}{chunk.id}",
        context_id=f"{OBSIDIAN_CONTEXT_ID_PREFIX}{chunk.note_id}",
        chunk_index=chunk.chunk_index,
        heading=chunk.heading_path,
        content=chunk.text,
        token_count=chunk.token_count,
        content_hash=chunk.content_hash,
        chunk_metadata=metadata,
        created_at=aware_utc_datetime(chunk.created_at),
    )


def raw_obsidian_chunk_id(chunk_id: str) -> str:
    """Resolve the raw Obsidian chunk identifier.

    Args:
        chunk_id: Chunk identifier to normalize.

    Returns:
        Normalized raw chunk identifier.
    """
    return chunk_id.removeprefix(OBSIDIAN_CHUNK_ID_PREFIX)
