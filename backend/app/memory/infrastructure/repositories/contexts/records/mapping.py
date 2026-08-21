"""Mapping helpers for Context Vault ORM rows."""

from __future__ import annotations

from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextRecord,
)
from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.infrastructure.models.context_models import (
    ContextAccessEventORM,
    ContextChunkORM,
    ContextORM,
)
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime


def _json_object(value: dict[str, JSONValue]) -> ContextMetadataPayload:
    metadata = ContextMetadataPayload()
    metadata.update(value.items())
    return metadata


def map_context_row(row: ContextORM) -> ContextRecord:
    """Map a context ORM row into a read model.

    Args:
        row: Context ORM row.

    Returns:
        Context read model.
    """
    context = ContextRecord(
        id=row.id,
        kind=ContextKind(row.kind),
        title=row.title,
        summary=row.summary,
        content=row.content,
        content_format=ContextContentFormat(row.content_format),
        project=row.project,
        scope=ContextScope(row.scope),
        workspace_id=row.workspace_id,
        agent_id=row.agent_id,
        user_id=row.user_id,
        session_id=row.session_id,
        visibility=ContextScope(row.visibility),
        source_agent=row.source_agent,
        source_type=ContextSourceType(row.source_type),
        importance=ContextImportance(row.importance),
        tags=tuple(row.tags),
        status=ContextStorageStatus(row.status),
        quality_score=row.quality_score,
        warnings=tuple(row.warnings),
        restore_prompt=row.restore_prompt,
        context_metadata=_json_object(row.context_metadata),
        created_at=aware_utc_datetime(row.created_at),
        updated_at=aware_utc_datetime(row.updated_at),
        last_accessed_at=aware_utc_datetime(row.last_accessed_at)
        if row.last_accessed_at is not None
        else None,
        expires_at=aware_utc_datetime(row.expires_at)
        if row.expires_at is not None
        else None,
        archived_at=aware_utc_datetime(row.archived_at)
        if row.archived_at is not None
        else None,
        access_count=row.access_count,
        is_archived=row.is_archived,
    )
    return context


def map_chunk_row(row: ContextChunkORM) -> ContextChunkRecord:
    """Map a context chunk ORM row into a read model.

    Args:
        row: Context chunk ORM row.

    Returns:
        Context chunk read model.
    """
    chunk = ContextChunkRecord(
        id=row.id,
        context_id=row.context_id,
        chunk_index=row.chunk_index,
        heading=row.heading,
        content=row.content,
        token_count=row.token_count,
        content_hash=row.content_hash,
        chunk_metadata=_json_object(row.chunk_metadata),
        created_at=aware_utc_datetime(row.created_at),
    )
    return chunk


def map_access_event_row(row: ContextAccessEventORM) -> ContextAccessEventRecord:
    """Map a context access event ORM row into a read model.

    Args:
        row: Context access event ORM row.

    Returns:
        Context access event read model.
    """
    event = ContextAccessEventRecord(
        id=row.id,
        context_id=row.context_id,
        accessed_at=aware_utc_datetime(row.accessed_at),
        actor_name=row.actor_name,
        actor_type=ContextAccessActorType(row.actor_type),
        access_method=ContextAccessMethod(row.access_method),
        source_surface=row.source_surface,
    )
    return event
