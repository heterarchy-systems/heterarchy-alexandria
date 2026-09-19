"""Obsidian index write-through and graph reconciliation store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianCompiledDocumentState,
    ObsidianNoteIndex,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
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


# protocol-contract: structural-seam
class ObsidianIndexChangeRecorder(Protocol):
    """Append one durable change record on the caller's active session.

    Implementations run inside the same transaction that commits the index
    write described by the record, so the record commits or rolls back with
    the indexed note state it describes.
    """

    async def __call__(
        self,
        session: AsyncSession,
        *,
        context_id: str,
        change_kind: str,
        content_hash: bytes,
        recorded_at: datetime,
    ) -> None:
        """Record one indexed-note change.

        Args:
            session: Active async session owning the surrounding tx.
            context_id: Canonical note identifier of the changed Context.
            change_kind: Recorded mutation kind.
            content_hash: Post-change content digest.
            recorded_at: Mutation timestamp shared with the indexed note.
        """


@dataclass(frozen=True, slots=True)
class _ContextChangeObservation:
    """One mechanically observed canonical Context transition."""

    change_kind: str
    content_hash: bytes


class ObsidianIndexWriteStore:
    """Write note metadata, chunks, FTS rows, and graph edges atomically."""

    def __init__(
        self,
        session: AsyncSession,
        context_change_recorder: ObsidianIndexChangeRecorder | None = None,
    ) -> None:
        """Create the write store.

        Args:
            session: Active async database session.
            context_change_recorder: Optional canonical Context change
                observer invoked inside the index-write transaction.
        """
        self._session = session
        self._context_change_recorder = context_change_recorder

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
        existed = model is not None
        previous_status = model.status if model is not None else None
        previous_content_hash = model.content_hash if model is not None else None
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
        model.source_hash = payload.source_hash or payload.content_hash
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
        await self._record_context_change(
            payload,
            existed=existed,
            previous_status=previous_status,
            previous_content_hash=previous_content_hash,
            recorded_at=now,
        )
        return note_from_model(model)

    async def _record_context_change(
        self,
        payload: ObsidianNoteIndex,
        *,
        existed: bool,
        previous_status: str | None,
        previous_content_hash: str | None,
        recorded_at: datetime,
    ) -> None:
        """Append one canonical Context change record inside the caller's tx.

        The observation is derived only from state seen at this write
        (created versus previously indexed row, previous lifecycle status,
        and the previous content hash); identical re-index writes record
        nothing, so the log reflects PG-observed state without fabricating
        provenance for past rows.

        Args:
            payload: Indexed note payload that was just committed to the tx.
            existed: Whether an indexed row for this note id already existed.
            previous_status: Lifecycle status observed before this write.
            previous_content_hash: Content hash observed before this write.
            recorded_at: Mutation timestamp shared with the indexed note.
        """
        if self._context_change_recorder is None:
            return
        if payload.alexandria_type is not AlexandriaNoteType.CONTEXT:
            return
        observation = _observed_context_change(
            payload,
            existed=existed,
            previous_status=previous_status,
            previous_content_hash=previous_content_hash,
        )
        if observation is None:
            return
        await self._context_change_recorder(
            self._session,
            context_id=payload.note_id,
            change_kind=observation.change_kind,
            content_hash=observation.content_hash,
            recorded_at=recorded_at,
        )

    async def list_indexed_note_identifiers(self) -> tuple[tuple[str, str], ...]:
        """Return every indexed note identity in the rebuildable projection.

        Returns:
            (note_id, relative_path) pairs for all indexed notes.
        """
        rows = await self._session.execute(
            select(ObsidianFileORM.note_id, ObsidianFileORM.relative_path)
        )
        return tuple((note_id, path) for note_id, path in rows.all())

    async def list_compiled_document_states(
        self,
    ) -> tuple[ObsidianCompiledDocumentState, ...]:
        """Return one batch-built previous compilation snapshot.

        Files, chunk hashes, and edge ids are loaded in three bounded queries so
        vault reindex can supply Rust with real previous state without an N+1
        read per note.
        """
        file_rows = (
            await self._session.execute(
                select(
                    ObsidianFileORM.note_id,
                    ObsidianFileORM.relative_path,
                    ObsidianFileORM.source_hash,
                )
                .where(
                    ObsidianFileORM.index_status == ObsidianIndexStatus.INDEXED.value,
                    ObsidianFileORM.source_hash.is_not(None),
                )
                .order_by(ObsidianFileORM.relative_path)
            )
        ).all()
        chunk_rows = (
            await self._session.execute(
                select(
                    ObsidianChunkORM.note_id,
                    ObsidianChunkORM.content_hash,
                ).order_by(ObsidianChunkORM.note_id, ObsidianChunkORM.chunk_index)
            )
        ).all()
        edge_rows = (
            await self._session.execute(
                select(
                    ObsidianEdgeORM.source_note_id,
                    ObsidianEdgeORM.edge_id,
                ).order_by(ObsidianEdgeORM.source_note_id, ObsidianEdgeORM.edge_id)
            )
        ).all()
        chunk_hashes_by_note: dict[str, list[str]] = {}
        for note_id, content_hash in chunk_rows:
            chunk_hashes_by_note.setdefault(note_id, []).append(content_hash)
        edge_ids_by_note: dict[str, list[str]] = {}
        for note_id, edge_id in edge_rows:
            edge_ids_by_note.setdefault(note_id, []).append(edge_id)
        return tuple(
            ObsidianCompiledDocumentState(
                note_id=note_id,
                relative_path=relative_path,
                source_hash=source_hash,
                chunk_hashes=tuple(chunk_hashes_by_note.get(note_id, ())),
                edge_ids=tuple(edge_ids_by_note.get(note_id, ())),
            )
            for note_id, relative_path, source_hash in file_rows
        )

    async def read_compiled_embedding_fingerprint_key(self) -> str | None:
        """Return the single persisted embedding generation across stored vectors.

        Missing vectors have a NULL fingerprint and are recovered independently
        by the bounded embedding-recovery path.  Only mixed non-NULL generations
        indicate a global embedding-policy mismatch for CompilePlan.
        """
        keys = tuple(
            (
                await self._session.execute(
                    select(ObsidianChunkORM.embedding_fingerprint_key)
                    .where(ObsidianChunkORM.embedding_fingerprint_key.is_not(None))
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        if len(keys) != 1:
            return None
        return keys[0]

    async def mark_documents_stale(self, relative_paths: tuple[str, ...]) -> int:
        """Discard indexed notes removed from the canonical scan.

        Args:
            relative_paths: Paths removed per the compile plan.

        Returns:
            Number of note indexes discarded.
        """
        if not relative_paths:
            return 0
        rows = await self._session.execute(
            select(ObsidianFileORM).where(
                ObsidianFileORM.relative_path.in_(relative_paths)
            )
        )
        discarded = 0
        for model in rows.scalars().all():
            await discard_obsidian_note_index(self._session, model.note_id)
            await self._session.delete(model)
            discarded += 1
        await self._session.flush()
        return discarded

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


def _observed_context_change(
    payload: ObsidianNoteIndex,
    *,
    existed: bool,
    previous_status: str | None,
    previous_content_hash: str | None,
) -> _ContextChangeObservation | None:
    """Resolve the mechanically observed transition of one canonical Context.

    Transition detection uses the lifecycle status and the note content hash
    (which covers the managed note body, not frontmatter scalars). A
    frontmatter-only patch that keeps the status and body identical — such as
    the replacement's lifecycle normalization during supersede — records
    nothing.

    Args:
        payload: Indexed note payload that was just written.
        existed: Whether an indexed row for this note id already existed.
        previous_status: Lifecycle status observed before this write.
        previous_content_hash: Content hash observed before this write.

    Returns:
        The observed change with its post-write content digest, or None when
        this write carries no observable transition (an identical re-index).
    """
    content_hash = bytes.fromhex(payload.content_hash)
    if not existed:
        return _ContextChangeObservation("created", content_hash)
    if previous_status != payload.status:
        if payload.status == "superseded":
            return _ContextChangeObservation("superseded", content_hash)
        if payload.status == "archived":
            return _ContextChangeObservation("archived", content_hash)
    if payload.content_hash == previous_content_hash:
        return None
    return _ContextChangeObservation("updated", content_hash)
