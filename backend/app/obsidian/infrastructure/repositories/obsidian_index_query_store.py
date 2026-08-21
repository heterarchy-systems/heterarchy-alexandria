"""Obsidian index read, search, and duplicate query store."""

from __future__ import annotations

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianContextDuplicateQuery,
    ObsidianSearchQuery,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianSearchHit,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_fts import (
    build_obsidian_fts_query,
)
from app.obsidian.infrastructure.repositories.obsidian_index_mapping import (
    matches_tags,
    note_from_model,
    obsidian_excerpt,
)
from app.obsidian.infrastructure.repositories.obsidian_index_row_cleanup import (
    get_obsidian_file_by_path,
)
from app.shared.infrastructure.postgres_fts_relevance import (
    postgres_fts_rank_to_score,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement


class ObsidianIndexQueryStore:
    """Read and search the rebuildable Obsidian index cache."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the query store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        """Read one indexed note by id.

        Args:
            note_id: Stable note id.

        Returns:
            Note entity when found.
        """
        model = await self._session.get(ObsidianFileORM, note_id)
        return None if model is None else note_from_model(model)

    async def get_by_path(self, relative_path: str) -> ObsidianNote | None:
        """Read one indexed note by vault-relative path.

        Args:
            relative_path: Vault-relative path.

        Returns:
            Note entity when found.
        """
        model = await get_obsidian_file_by_path(self._session, relative_path)
        return None if model is None else note_from_model(model)

    async def find_context_duplicate(
        self,
        query: ObsidianContextDuplicateQuery,
    ) -> ObsidianNote | None:
        """Return an indexed Context with the same scope identity and body hash.

        Args:
            query: Canonical duplicate lookup constraints.

        Returns:
            Existing duplicate Context when found.
        """
        frontmatter = ObsidianFileORM.frontmatter_json

        def extract(field_name: str) -> ColumnElement[str]:
            return func.json_extract_path_text(frontmatter, field_name)

        statement = select(ObsidianFileORM).where(
            ObsidianFileORM.note_id != query.excluded_note_id,
            ObsidianFileORM.alexandria_type == "context",
            ObsidianFileORM.index_status == ObsidianIndexStatus.INDEXED.value,
            func.upper(extract("scope")) == query.scope,
            extract("content_hash") == query.content_hash,
        )
        identity_filters = (
            ("project", query.project),
            ("workspace_id", query.workspace_id),
            ("agent_id", query.agent_id),
            ("user_id", query.user_id),
            ("session_id", query.session_id),
        )
        for field_name, field_value in identity_filters:
            column = extract(field_name)
            statement = statement.where(
                column.is_(None) if field_value is None else column == field_value
            )
        model = await self._session.scalar(statement.limit(1))
        return None if model is None else note_from_model(model)

    async def search(self, query: ObsidianSearchQuery) -> list[ObsidianSearchHit]:
        """Search notes using FTS and indexed metadata filters.

        Args:
            query: Search filters and query text.

        Returns:
            Ranked search hits.
        """
        fts_query = build_obsidian_fts_query(
            query.query,
            limit=query.limit,
            alexandria_type=query.alexandria_type,
            excluded_alexandria_types=query.excluded_alexandria_types,
            project=query.project,
            tags=query.tags,
        )
        if fts_query is None:
            return await _recent_notes(self._session, query)
        candidate_statement = fts_query.statement.limit(None).subquery()
        best_chunk_per_note = (
            select(
                candidate_statement.c.id,
                candidate_statement.c.note_id,
                candidate_statement.c.rank,
            )
            .distinct(candidate_statement.c.note_id)
            .order_by(candidate_statement.c.note_id, candidate_statement.c.rank.desc())
            .subquery()
        )
        statement = (
            select(
                best_chunk_per_note.c.id,
                best_chunk_per_note.c.note_id,
                best_chunk_per_note.c.rank,
            )
            .order_by(best_chunk_per_note.c.rank.desc())
            .limit(query.limit)
        )
        rows = await self._session.execute(
            statement,
            {
                key: value
                for key, value in fts_query.parameters.items()
                if key != "limit"
            },
        )
        ranked_rows = [
            (str(chunk_id), str(note_id), float(rank))
            for chunk_id, note_id, rank in rows.all()
        ]
        if not ranked_rows:
            return []
        note_ids = {note_id for _, note_id, _ in ranked_rows}
        chunk_ids = {chunk_id for chunk_id, _, _ in ranked_rows}
        note_models = (
            await self._session.scalars(
                select(ObsidianFileORM).where(ObsidianFileORM.note_id.in_(note_ids))
            )
        ).all()
        notes = {model.note_id: note_from_model(model) for model in note_models}
        chunk_rows = (
            await self._session.execute(
                select(
                    ObsidianChunkORM.id,
                    ObsidianChunkORM.text,
                    ObsidianChunkORM.heading_path,
                ).where(ObsidianChunkORM.id.in_(chunk_ids))
            )
        ).all()
        chunks = {
            str(chunk_id): (str(text), heading_path)
            for chunk_id, text, heading_path in chunk_rows
        }
        hits: list[ObsidianSearchHit] = []
        for chunk_id, note_id, rank in ranked_rows:
            note = notes.get(note_id)
            if note is None:
                continue
            if note.index_status != ObsidianIndexStatus.INDEXED:
                continue
            chunk = chunks.get(chunk_id)
            chunk_text = note.body if chunk is None else str(chunk[0])
            heading_path = None if chunk is None else chunk[1]
            excerpt = obsidian_excerpt(chunk_text)
            hits.append(
                ObsidianSearchHit(
                    note=note,
                    excerpt=excerpt,
                    score=postgres_fts_rank_to_score(rank),
                    chunk_id=chunk_id,
                    heading_path=heading_path,
                )
            )
        return hits

    async def count_by_status(self) -> tuple[int, int, int]:
        """Return indexed, stale, and error note counts.

        Returns:
            Tuple of indexed, stale, and error note counts.
        """
        rows = await self._session.execute(
            select(ObsidianFileORM.index_status, func.count()).group_by(
                ObsidianFileORM.index_status
            )
        )
        counts = {str(status): int(count) for status, count in rows.all()}
        return (
            counts.get(ObsidianIndexStatus.INDEXED.value, 0),
            counts.get(ObsidianIndexStatus.STALE.value, 0),
            counts.get(ObsidianIndexStatus.ERROR.value, 0),
        )


async def _recent_notes(
    session: AsyncSession,
    query: ObsidianSearchQuery,
) -> list[ObsidianSearchHit]:
    statement = select(ObsidianFileORM).where(
        ObsidianFileORM.index_status == ObsidianIndexStatus.INDEXED.value
    )
    if query.alexandria_type is not None:
        statement = statement.where(
            ObsidianFileORM.alexandria_type == query.alexandria_type.value
        )
    if query.excluded_alexandria_types:
        statement = statement.where(
            ObsidianFileORM.alexandria_type.not_in(
                [note_type.value for note_type in query.excluded_alexandria_types]
            )
        )
    if query.project is not None:
        statement = statement.where(ObsidianFileORM.project == query.project)
    statement = statement.order_by(ObsidianFileORM.modified_at.desc()).limit(
        query.limit
    )
    rows = await session.execute(statement)
    return [
        ObsidianSearchHit(
            note=note_from_model(model),
            excerpt=obsidian_excerpt(model.body),
            score=0.0,
        )
        for model in rows.scalars().all()
        if matches_tags(model.tags, query.tags)
    ]
