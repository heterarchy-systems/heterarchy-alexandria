"""FTS and vector query store for Obsidian-backed Context recall."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import batched
from typing import cast

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, bindparam, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql.elements import ColumnElement

from app.memory.application.retrieval.ranking.vector_scoring import (
    cosine_distance_to_score,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import (
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
)
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_context_mapping import (
    DEFAULT_EXCLUDED_OBSIDIAN_RECALL_PREFIXES,
    context_record_from_obsidian_row,
    match_from_obsidian_rows,
    matches_context_filters,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_recall_policy import (
    _candidate_limit,
    _obsidian_scope_recall_clause,
    _recall_visibility_conditions,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_fts import (
    build_obsidian_fts_query,
)
from app.shared.infrastructure.postgres_fts_relevance import (
    postgres_fts_rank_to_score,
)
from app.shared.types.extra_types import JSONObject, JSONValue

type RankedObsidianCandidate = tuple[str, str, float]
type HydratedObsidianCandidate = tuple[ObsidianFileORM, ObsidianChunkORM, float]


class ObsidianContextQueryStore:
    """Execute Obsidian-backed Context FTS and vector queries."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the shared async database session.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        """Search indexed Obsidian note chunks through PostgreSQL FTS.

        Args:
            recall: Validated FTS query and recall filters.

        Returns:
            Obsidian-backed matches mapped into Context RAG read models.
        """
        recall_filter = recall.recall_filter
        scope_filter = recall_filter.scope_identity
        fts_query = build_obsidian_fts_query(
            recall.query,
            limit=_candidate_limit(recall_filter.limit),
            included_statuses=list(
                ContextRecallLifecycleStatus.obsidian_values(
                    recall_filter.lifecycle_statuses
                )
            ),
            excluded_path_prefixes=list(DEFAULT_EXCLUDED_OBSIDIAN_RECALL_PREFIXES),
            project=None,
        )
        if fts_query is None:
            return []
        statement = fts_query.statement
        parameters = dict(fts_query.parameters)
        obsidian_table = ObsidianFileORM.__table__
        statement = statement.where(
            _obsidian_scope_recall_clause(
                obsidian_table.c.frontmatter_json,
                obsidian_table.c.project,
                obsidian_table.c.alexandria_type,
                scope_filter,
            )
        )
        parameters.update(scope_filter.sql_parameters())
        rows = await self._session.execute(statement, parameters)
        ranked = [(str(row[0]), str(row[1]), float(row[2])) for row in rows.all()]
        matches: list[ContextSearchMatch] = []
        contexts_by_note_id: dict[str, ContextRecord] = {}
        for ranked_batch in batched(ranked, recall_filter.limit, strict=False):
            candidates = await self._hydrate_ranked_candidates(ranked_batch)
            for note, chunk, rank in candidates:
                if not chunk.text.strip():
                    continue
                context = contexts_by_note_id.get(note.note_id)
                if context is None:
                    context = context_record_from_obsidian_row(note)
                    contexts_by_note_id[note.note_id] = context
                if not matches_context_filters(
                    note,
                    context,
                    recall_filter.kind,
                    scope_filter,
                    project=scope_filter.project,
                    include_lifecycle_statuses=recall_filter.lifecycle_statuses,
                ):
                    continue
                fts_score = postgres_fts_rank_to_score(rank)
                matches.append(
                    match_from_obsidian_rows(
                        note=note,
                        chunk=chunk,
                        context=context,
                        score=fts_score,
                        fts_score=fts_score,
                        vector_score=None,
                        why_retrieved=_fts_reason(note.frontmatter_json, recall.query),
                    )
                )
                if len(matches) >= recall_filter.limit:
                    return matches
        return matches

    async def search_vector(
        self, recall: ContextVectorRecall
    ) -> list[ContextSearchMatch]:
        """Search indexed Obsidian note chunks through pgvector.

        Args:
            recall: Validated vector query and recall filters.

        Returns:
            Obsidian-backed vector matches mapped into Context RAG read models.
        """
        recall_filter = recall.recall_filter
        scope_filter = recall_filter.scope_identity
        query_embedding = list(recall.query_embedding)
        distance = cast(
            ColumnElement[float],
            ObsidianChunkORM.embedding.op("<=>", return_type=Float)(
                bindparam("query_embedding", type_=Vector(recall.dimensions))
            ).label("distance"),
        )
        statement = (
            select(
                ObsidianChunkORM.id,
                ObsidianChunkORM.note_id,
                distance,
            )
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(
                ObsidianChunkORM.embedding.is_not(None),
                ObsidianChunkORM.embedding_model == bindparam("model_name"),
                ObsidianChunkORM.embedding_dimensions == bindparam("dimensions"),
                ObsidianChunkORM.embedding_fingerprint_key
                == bindparam("fingerprint_key"),
                *_recall_visibility_conditions(recall_filter.lifecycle_statuses),
            )
            .order_by(distance.asc())
            .limit(bindparam("limit"))
        )
        parameters: dict[str, list[float] | str | int] = {
            "query_embedding": query_embedding,
            "model_name": recall.model_name,
            "dimensions": recall.dimensions,
            "fingerprint_key": recall.fingerprint_key,
            "limit": _candidate_limit(recall_filter.limit),
        }
        obsidian_table = ObsidianFileORM.__table__
        statement = statement.where(
            _obsidian_scope_recall_clause(
                obsidian_table.c.frontmatter_json,
                obsidian_table.c.project,
                obsidian_table.c.alexandria_type,
                scope_filter,
            )
        )
        parameters.update(scope_filter.sql_parameters())
        rows = await self._session.execute(statement, parameters)
        ranked = [(str(row[0]), str(row[1]), float(row[2])) for row in rows.all()]
        matches: list[ContextSearchMatch] = []
        contexts_by_note_id: dict[str, ContextRecord] = {}
        for ranked_batch in batched(ranked, recall_filter.limit, strict=False):
            candidates = await self._hydrate_ranked_candidates(ranked_batch)
            for note, chunk, distance_value in candidates:
                if not chunk.text.strip():
                    continue
                context = contexts_by_note_id.get(note.note_id)
                if context is None:
                    context = context_record_from_obsidian_row(note)
                    contexts_by_note_id[note.note_id] = context
                if not matches_context_filters(
                    note,
                    context,
                    recall_filter.kind,
                    scope_filter,
                    project=scope_filter.project,
                    include_lifecycle_statuses=recall_filter.lifecycle_statuses,
                ):
                    continue
                vector_score = cosine_distance_to_score(distance_value)
                matches.append(
                    match_from_obsidian_rows(
                        note=note,
                        chunk=chunk,
                        context=context,
                        score=vector_score,
                        fts_score=None,
                        vector_score=vector_score,
                        why_retrieved=(
                            "Matched Obsidian vault note chunk with pgvector semantic embedding distance."
                        ),
                    )
                )
                if len(matches) >= recall_filter.limit:
                    return matches
        return matches

    async def _hydrate_ranked_candidates(
        self,
        ranked: Sequence[RankedObsidianCandidate],
    ) -> list[HydratedObsidianCandidate]:
        """Load ranked note and chunk rows with two bounded SQL queries.

        Args:
            ranked: Candidate chunk id, note id, and score tuples in rank order.

        Returns:
            Available note and chunk rows restored in the original rank order.
        """
        if not ranked:
            return []
        note_ids = tuple(dict.fromkeys(note_id for _, note_id, _ in ranked))
        chunk_ids = tuple(dict.fromkeys(chunk_id for chunk_id, _, _ in ranked))
        notes = {
            note.note_id: note
            for note in (
                await self._session.scalars(
                    select(ObsidianFileORM).where(ObsidianFileORM.note_id.in_(note_ids))
                )
            ).all()
        }
        chunks = {
            chunk.id: chunk
            for chunk in (
                await self._session.scalars(
                    select(ObsidianChunkORM)
                    .options(
                        load_only(
                            ObsidianChunkORM.id,
                            ObsidianChunkORM.note_id,
                            ObsidianChunkORM.chunk_index,
                            ObsidianChunkORM.heading_path,
                            ObsidianChunkORM.text,
                            ObsidianChunkORM.token_count,
                            ObsidianChunkORM.content_hash,
                            ObsidianChunkORM.created_at,
                        )
                    )
                    .where(ObsidianChunkORM.id.in_(chunk_ids))
                )
            ).all()
        }
        hydrated: list[HydratedObsidianCandidate] = []
        for chunk_id, note_id, score in ranked:
            note = notes.get(note_id)
            chunk = chunks.get(chunk_id)
            if note is None or chunk is None or chunk.note_id != note_id:
                continue
            hydrated.append((note, chunk, score))
        return hydrated


def _fts_reason(frontmatter: JSONObject, query: str) -> str:
    """Return bounded FTS provenance, including declared alias evidence."""
    normalized_query = _normalized_alias(query)
    for field_name in ("aliases", "report_aliases"):
        value: JSONValue | None = frontmatter.get(field_name)
        values = (
            [value]
            if isinstance(value, str)
            else value
            if isinstance(value, list)
            else []
        )
        if any(
            isinstance(item, str) and _normalized_alias(item) == normalized_query
            for item in values
        ):
            return "Matched declared Obsidian alias with PostgreSQL full-text search."
    return "Matched Obsidian vault note chunk with PostgreSQL full-text search."


def _normalized_alias(value: str) -> str:
    """Normalize an alias using the canonical case and whitespace semantics."""
    return " ".join(value.casefold().split())
