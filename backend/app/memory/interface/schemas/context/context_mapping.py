"""Context Vault schema payload mappers."""

from __future__ import annotations

from app.memory.application.retrieval.context_retrieval_metadata import (
    canonical_context_id,
    lifecycle_metadata,
    lifecycle_status,
    provenance_metadata,
    retrieval_metadata,
)
from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextPack,
    ContextRecord,
    ContextReindexResult,
    ContextSearchMatch,
    ContextSoftRebuildResult,
    RagDependencyHealth,
)
from app.memory.domain.types.context_payload_types import (
    ContextAccessEventPayload,
    ContextChunkPayload,
    ContextEmbeddingSourceStatusPayload,
    ContextGraphEvidencePayload,
    ContextLifecyclePayload,
    ContextPackPayload,
    ContextPayload,
    ContextProvenancePayload,
    ContextReindexPayload,
    ContextSearchMatchPayload,
    ContextSoftRebuildPayload,
    RagHealthPayload,
)


def context_payload(context: ContextRecord) -> ContextPayload:
    """Return an API payload for one stored context.

    Args:
        context: Stored context read model.

    Returns:
        Typed response payload for the context API boundary.
    """
    provenance = provenance_metadata(context)
    lifecycle = lifecycle_metadata(context)
    provenance_payload = ContextProvenancePayload(
        source_actor_id=provenance.source_actor_id,
        source_actor_type=provenance.source_actor_type,
        source_run_id=provenance.source_run_id,
        external_run_id=provenance.external_run_id,
        artifact_refs=list(provenance.artifact_refs),
        evidence_refs=list(provenance.evidence_refs),
        confidence=provenance.confidence,
    )
    lifecycle_payload = ContextLifecyclePayload(
        status=lifecycle.status,
        content_hash=lifecycle.content_hash,
        version=lifecycle.version,
        supersedes_context_id=lifecycle.supersedes_context_id,
        superseded_by_context_id=lifecycle.superseded_by_context_id,
    )
    payload: ContextPayload = {
        "id": context.id,
        "canonical_context_id": canonical_context_id(context),
        "kind": context.kind,
        "memory_function": context.memory_function,
        "title": context.title,
        "summary": context.summary,
        "content": context.content,
        "content_format": context.content_format,
        "project": context.project,
        "scope": context.scope,
        "workspace_id": context.workspace_id,
        "agent_id": context.agent_id,
        "user_id": context.user_id,
        "session_id": context.session_id,
        "visibility": context.visibility,
        "source_agent": context.source_agent,
        "source_type": context.source_type,
        "importance": context.importance,
        "tags": list(context.tags),
        "status": context.status,
        "lifecycle_status": lifecycle_status(context),
        "provenance": provenance_payload,
        "lifecycle": lifecycle_payload,
        "quality_score": context.quality_score,
        "warnings": list(context.warnings),
        "restore_prompt": context.restore_prompt,
        "metadata": context.context_metadata,
        "created_at": context.created_at,
        "updated_at": context.updated_at,
        "last_accessed_at": context.last_accessed_at,
        "expires_at": context.expires_at,
        "archived_at": context.archived_at,
        "access_count": context.access_count,
        "is_archived": context.is_archived,
    }
    return payload


def chunk_payload(chunk: ContextChunkRecord) -> ContextChunkPayload:
    """Return an API payload for one stored context chunk.

    Args:
        chunk: Stored context chunk read model.

    Returns:
        Typed response payload for the context chunk API boundary.
    """
    payload: ContextChunkPayload = {
        "id": chunk.id,
        "context_id": chunk.context_id,
        "chunk_index": chunk.chunk_index,
        "heading": chunk.heading,
        "content": chunk.content,
        "token_count": chunk.token_count,
        "content_hash": chunk.content_hash,
        "metadata": chunk.chunk_metadata,
        "created_at": chunk.created_at,
    }
    return payload


def access_event_payload(
    event: ContextAccessEventRecord,
) -> ContextAccessEventPayload:
    """Return an API payload for one context access event.

    Args:
        event: Stored access event read model.

    Returns:
        Typed response payload for the context access event API boundary.
    """
    payload: ContextAccessEventPayload = {
        "id": event.id,
        "context_id": event.context_id,
        "accessed_at": event.accessed_at,
        "actor_name": event.actor_name,
        "actor_type": event.actor_type,
        "access_method": event.access_method,
        "source_surface": event.source_surface,
    }
    return payload


def match_payload(match: ContextSearchMatch) -> ContextSearchMatchPayload:
    """Return an API payload for one context search match.

    Args:
        match: Context search match read model.

    Returns:
        Typed response payload for one retrieved match.
    """
    metadata = retrieval_metadata(match)
    graph_evidence = [
        ContextGraphEvidencePayload(
            signal=item.signal,
            relation=item.relation,
            direction=item.direction,
            source_context_id=item.source_context_id,
            target_context_id=item.target_context_id,
            target_title=item.target_title,
            distance=item.distance,
            evidence_ref=item.evidence_ref,
        )
        for item in match.graph_evidence
    ]
    payload: ContextSearchMatchPayload = {
        "context": context_payload(match.context),
        "chunk": chunk_payload(match.chunk),
        "score": match.score,
        "fts_score": match.fts_score,
        "vector_score": match.vector_score,
        "graph_score": match.graph_score,
        "why_retrieved": match.why_retrieved,
        "canonical_context_id": metadata.canonical_context_id,
        "lifecycle_status": metadata.lifecycle_status,
        "source": metadata.retrieval_source,
        "retrieval_strategy": metadata.retrieval_strategy,
        "graph_evidence": graph_evidence or None,
    }
    return payload


def pack_payload(pack: ContextPack) -> ContextPackPayload:
    """Return an API payload for a RAG Context Pack.

    Args:
        pack: Context Pack read model.

    Returns:
        Typed response payload for the RAG Context Pack API boundary.
    """
    payload: ContextPackPayload = {
        "query": pack.query,
        "strategy": pack.strategy,
        "effective_strategy": pack.effective_strategy,
        "warnings": list(pack.warnings),
        "recall_scopes": list(pack.recall_scopes),
        "matches": [match_payload(match) for match in pack.matches],
        "context_pack": pack.context_pack,
    }
    return payload


def health_payload(health: RagDependencyHealth) -> RagHealthPayload:
    """Return an API payload for RAG dependency health.

    Args:
        health: RAG dependency health read model.

    Returns:
        Typed response payload for RAG dependency health.
    """
    payload: RagHealthPayload = {
        "fts": health.fts,
        "vector": health.vector,
        "embedding": health.embedding,
        "default_strategy": health.default_strategy,
        "model_name": health.model_name,
        "dimensions": health.dimensions,
        "fingerprint": health.fingerprint,
        "warnings": list(health.warnings),
        "source_statuses": [
            source_status_payload(status) for status in health.source_statuses
        ],
    }
    return payload


def reindex_payload(result: ContextReindexResult) -> ContextReindexPayload:
    """Return an API payload for context embedding reindex results.

    Args:
        result: Reindex result read model.

    Returns:
        Typed response payload for reindex results.
    """
    payload = ContextReindexPayload(
        scanned=result.scanned,
        updated=result.updated,
        skipped=result.skipped,
        warnings=list(result.warnings),
    )
    return payload


def source_status_payload(
    status: ContextEmbeddingSourceStatus,
) -> ContextEmbeddingSourceStatusPayload:
    """Return an API payload for source embedding diagnostics.

    Args:
        status: Source embedding status read model.

    Returns:
        Typed response payload for one source status.
    """
    payload: ContextEmbeddingSourceStatusPayload = {
        "source_name": status.source_name,
        "status": status.status,
        "total_rows": status.total_rows,
        "current_rows": status.current_rows,
        "stale_rows": status.stale_rows,
        "missing_rows": status.missing_rows,
        "current_fingerprint": status.current_fingerprint,
        "stored_fingerprints": list(status.stored_fingerprints),
    }
    return payload


def soft_rebuild_payload(
    result: ContextSoftRebuildResult,
) -> ContextSoftRebuildPayload:
    """Return an API payload for soft embedding rebuild results.

    Args:
        result: Soft rebuild read model.

    Returns:
        Typed response payload for soft rebuild results.
    """
    payload: ContextSoftRebuildPayload = {
        "mode": result.mode,
        "source_preservation": result.source_preservation,
        "hard_delete_performed": result.hard_delete_performed,
        "before": health_payload(result.before),
        "source_status_before": [
            source_status_payload(status) for status in result.source_status_before
        ],
        "reindex": reindex_payload(result.reindex),
        "after": health_payload(result.after),
        "source_status_after": [
            source_status_payload(status) for status in result.source_status_after
        ],
        "verification_query": result.verification_query,
        "verification_matches": result.verification_matches,
        "verification_context_ids": list(result.verification_context_ids),
        "verification_warnings": list(result.verification_warnings),
        "warnings": list(result.warnings),
    }
    return payload
