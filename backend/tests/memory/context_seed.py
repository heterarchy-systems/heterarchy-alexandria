"""Test helpers for seeding Context Vault read/index fixtures."""

from __future__ import annotations

from datetime import datetime

from app.memory.application.retrieval.chunker import chunk_markdown
from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.application.retrieval.embeddings.embedding_document import (
    build_embedding_document_text,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.infrastructure.models.context_models import ContextChunkORM, ContextORM
from app.memory.infrastructure.repositories.contexts.records.mapping import (
    map_context_row,
)
from app.shared.types.embedding_types import normalize_embedding_vector
from app.shared.types.types_convert_utils import now_utc
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_context(
    session: AsyncSession,
    *,
    kind: ContextKind = ContextKind.HANDOFF,
    title: str = "Seeded handoff",
    summary: str = "Seeded context for retrieval tests.",
    content: str,
    project: str | None = None,
    scope: ContextScope | None = None,
    workspace_id: str | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    visibility: ContextScope | None = None,
    source_agent: str = "Hermes",
    source_type: ContextSourceType = ContextSourceType.AGENT,
    importance: ContextImportance = ContextImportance.MEDIUM,
    tags: list[str] | None = None,
    status: ContextStorageStatus = ContextStorageStatus.SAVED,
    quality_score: int = 100,
    warnings: list[str] | None = None,
    restore_prompt: str | None = None,
    context_metadata: ContextMetadataPayload | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> ContextRecord:
    """Seed a context row, chunk rows, and FTS rows for read-path tests.

    Args:
        session: Active test database session.
        content: Markdown content to chunk and index.
        embedding_provider: Optional deterministic embedding provider for
            vector-search test fixtures.

    Returns:
        Seeded context read model.
    """
    now = now_utc()
    resolved_scope = (
        ContextScope.PROJECT
        if scope is None and project is not None
        else ContextScope.GLOBAL
        if scope is None
        else scope
    )
    resolved_visibility = resolved_scope if visibility is None else visibility
    model = ContextORM(
        kind=kind.value,
        title=title,
        summary=summary,
        content=content,
        content_format=ContextContentFormat.MARKDOWN.value,
        project=project,
        scope=resolved_scope.value,
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
        visibility=resolved_visibility.value,
        source_agent=source_agent,
        source_type=source_type.value,
        importance=importance.value,
        tags=[] if tags is None else tags,
        status=status.value,
        quality_score=quality_score,
        warnings=[] if warnings is None else warnings,
        restore_prompt=restore_prompt,
        context_metadata={} if context_metadata is None else context_metadata,
        created_at=now if created_at is None else created_at,
        updated_at=now if updated_at is None else updated_at,
        expires_at=None,
        access_count=0,
        is_archived=False,
    )
    session.add(model)
    await session.flush()

    markdown_chunks = list(chunk_markdown(title=title, content=content))
    embedding_texts = [
        build_embedding_document_text(
            content=chunk.content,
            title=title,
            heading=chunk.heading,
        )
        for chunk in markdown_chunks
    ]
    embeddings = (
        embedding_provider.embed_documents(embedding_texts)
        if embedding_provider is not None
        else [None for _ in markdown_chunks]
    )
    fingerprint = (
        None if embedding_provider is None else embedding_provider.fingerprint()
    )
    chunk_rows: list[ContextChunkORM] = []
    for chunk, embedding in zip(markdown_chunks, embeddings, strict=True):
        chunk_row = ContextChunkORM(
            context_id=model.id,
            chunk_index=chunk.chunk_index,
            heading=chunk.heading,
            content=chunk.content,
            token_count=chunk.token_count,
            content_hash=chunk.content_hash,
            embedding=None
            if embedding is None
            else normalize_embedding_vector(embedding),
            embedding_model=None
            if embedding is None or embedding_provider is None
            else embedding_provider.model_name,
            embedding_dimensions=None
            if embedding is None or embedding_provider is None
            else embedding_provider.dimensions,
            embedding_provider=None if fingerprint is None else fingerprint.provider,
            embedding_provider_version=None
            if fingerprint is None
            else fingerprint.provider_version,
            embedding_pooling_mode=None
            if fingerprint is None
            else fingerprint.pooling_mode,
            embedding_normalize=None if fingerprint is None else fingerprint.normalize,
            embedding_fingerprint_key=None
            if fingerprint is None
            else fingerprint.key(),
            embedding_fingerprint_json=None
            if fingerprint is None
            else fingerprint.snapshot_payload(indexed_at=now),
            embedding_indexed_at=None if fingerprint is None else now,
            chunk_metadata=chunk.metadata,
            created_at=now,
        )
        chunk_rows.append(chunk_row)
    session.add_all(chunk_rows)
    await session.flush()

    return map_context_row(model)
