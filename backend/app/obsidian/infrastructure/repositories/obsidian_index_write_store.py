"""Obsidian index write-through and graph reconciliation store."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianNoteIndex,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianEdgeORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_chunk_embeddings import (
    existing_chunk_embeddings,
)
from app.obsidian.infrastructure.repositories.obsidian_index_mapping import (
    note_from_model,
)
from app.obsidian.infrastructure.repositories.obsidian_index_row_cleanup import (
    discard_obsidian_note_index,
    get_obsidian_file_by_path,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianIndexWriteError
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import aware_utc_datetime


class ObsidianIndexWriteStore:
    """Write note metadata, chunks, FTS rows, and graph edges atomically."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the write store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def upsert_note(self, payload: ObsidianNoteIndex) -> ObsidianNote:
        """Create or update one indexed note and its chunks.

        Args:
            payload: Indexed note payload.

        Returns:
            Persisted note entity.
        """
        try:
            async with self._session.begin_nested():
                return await self._upsert_note(payload)
        except SQLAlchemyError as exc:
            raise ObsidianIndexWriteError(
                f"failed to index Obsidian note: {payload.relative_path}"
            ) from exc

    async def _upsert_note(self, payload: ObsidianNoteIndex) -> ObsidianNote:
        """Execute upsert note.

        Args:
            payload: Validated payload for this operation.

        Returns:
            ObsidianNote result produced by upsert note.
        """
        now = datetime.now(UTC)
        path_model = await get_obsidian_file_by_path(
            self._session, payload.relative_path
        )
        model = await self._session.get(ObsidianFileORM, payload.note_id)
        if path_model is not None and path_model.note_id != payload.note_id:
            await discard_obsidian_note_index(self._session, path_model.note_id)
            await self._session.delete(path_model)
            await self._session.flush()
        if model is None:
            model = ObsidianFileORM(note_id=payload.note_id)
            self._session.add(model)
        model.relative_path = payload.relative_path
        model.alexandria_type = payload.alexandria_type.value
        model.title = payload.title
        model.status = payload.status
        model.tags = list(payload.tags)
        model.project = payload.project
        model.source = payload.source
        model.content_hash = payload.content_hash
        model.frontmatter_json = payload.frontmatter
        model.body = payload.body
        model.index_status = ObsidianIndexStatus.INDEXED.value
        model.error_message = None
        model.size_bytes = payload.size_bytes
        model.modified_at = aware_utc_datetime(payload.modified_at)
        model.indexed_at = now
        await self._replace_chunks(payload, now=now)
        await self._replace_edges(payload, now=now)
        await self._session.flush()
        return note_from_model(model)

    async def mark_missing_stale(self, relative_paths: set[str]) -> int:
        """Discard derived index rows for notes absent from canonical Markdown.

        Args:
            relative_paths: Paths observed during the current scan.

        Returns:
            Number of missing note indexes discarded.
        """
        statement = select(ObsidianFileORM)
        if relative_paths:
            statement = statement.where(
                ObsidianFileORM.relative_path.not_in(relative_paths)
            )
        rows = await self._session.execute(statement)
        discarded = 0
        for model in rows.scalars().all():
            await discard_obsidian_note_index(self._session, model.note_id)
            await self._session.delete(model)
            discarded += 1
        await self._session.flush()
        return discarded

    async def resolve_edge_targets(self) -> int:
        """Resolve late-indexed edge target ids from canonical target paths.

        Returns:
            Number of edge rows updated with a target note id.
        """
        rows = await self._session.execute(
            select(ObsidianEdgeORM).where(ObsidianEdgeORM.target_note_id.is_(None))
        )
        resolved = 0
        for edge in rows.scalars().all():
            target = await get_obsidian_file_by_path(self._session, edge.target_path)
            if (
                target is None
                or target.index_status != ObsidianIndexStatus.INDEXED.value
            ):
                continue
            edge.target_note_id = target.note_id
            resolved += 1
        await self._session.flush()
        return resolved

    async def _replace_chunks(
        self,
        payload: ObsidianNoteIndex,
        now: datetime,
    ) -> None:
        """Execute replace chunks.

        Args:
            payload: Validated payload for this operation.
            now: Now used by this operation.
        """
        with self._session.no_autoflush:
            existing_embeddings = await existing_chunk_embeddings(
                session=self._session,
                note_id=payload.note_id,
            )
        await self._session.execute(
            delete(ObsidianChunkORM).where(ObsidianChunkORM.note_id == payload.note_id)
        )
        chunk_models: list[ObsidianChunkORM] = []
        for chunk in payload.chunks:
            chunk_id = new_uuid()
            embedding = existing_embeddings.get((chunk.chunk_index, chunk.content_hash))
            chunk_models.append(
                ObsidianChunkORM(
                    id=chunk_id,
                    note_id=payload.note_id,
                    chunk_index=chunk.chunk_index,
                    heading_path=chunk.heading_path,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    content_hash=chunk.content_hash,
                    embedding=None if embedding is None else embedding.embedding,
                    embedding_model=None if embedding is None else embedding.model,
                    embedding_dimensions=None
                    if embedding is None
                    else embedding.dimensions,
                    embedding_provider=None
                    if embedding is None
                    else embedding.provider,
                    embedding_provider_version=None
                    if embedding is None
                    else embedding.provider_version,
                    embedding_pooling_mode=None
                    if embedding is None
                    else embedding.pooling_mode,
                    embedding_normalize=None
                    if embedding is None
                    else embedding.normalize,
                    embedding_fingerprint_key=None
                    if embedding is None
                    else embedding.fingerprint_key,
                    embedding_fingerprint_json=None
                    if embedding is None
                    else embedding.fingerprint,
                    embedding_indexed_at=None
                    if embedding is None
                    else embedding.indexed_at,
                    created_at=now,
                )
            )
        self._session.add_all(chunk_models)

    async def _replace_edges(
        self,
        payload: ObsidianNoteIndex,
        now: datetime,
    ) -> None:
        """Execute replace edges.

        Args:
            payload: Validated payload for this operation.
            now: Now used by this operation.
        """
        await self._session.execute(
            delete(ObsidianEdgeORM).where(
                ObsidianEdgeORM.source_note_id == payload.note_id
            )
        )
        edge_models: list[ObsidianEdgeORM] = []
        for edge in payload.edges:
            target_note_id = edge.target_note_id
            if target_note_id is None:
                target = await get_obsidian_file_by_path(
                    self._session, edge.target_path
                )
                target_note_id = None if target is None else target.note_id
            edge_models.append(
                ObsidianEdgeORM(
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    source_path=edge.source_path,
                    target_note_id=target_note_id,
                    target_path=edge.target_path,
                    relation=edge.relation.value,
                    confidence=edge.confidence,
                    source_kind=edge.source_kind.value,
                    created_at=now,
                    indexed_at=now,
                )
            )
        self._session.add_all(edge_models)
