"""FTS search execution for Context Vault chunks."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.contracts.context_recall_contracts import ContextFtsRecall
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.infrastructure.models.context_models import ContextChunkORM, ContextORM
from app.memory.infrastructure.repositories.contexts.records.mapping import (
    map_chunk_row,
    map_context_row,
)
from app.memory.infrastructure.repositories.contexts.search.fts import (
    build_context_fts_query,
)
from app.shared.infrastructure.postgres_fts_relevance import (
    postgres_fts_rank_to_score,
)


async def search_context_fts(
    session: AsyncSession, recall: ContextFtsRecall
) -> list[ContextSearchMatch]:
    """Search context chunks with the active lexical-search backend.

    Args:
        session: Active async database session.
        recall: Validated FTS query and recall filters.

    Returns:
        Ranked context matches.
    """
    fts_query = build_context_fts_query(recall)
    if fts_query is None:
        return []
    rows = await session.execute(fts_query.statement, dict(fts_query.parameters))
    ranked = [(str(row[0]), str(row[1]), float(row[2])) for row in rows.all()]
    if not ranked:
        return []

    chunk_ids = [chunk_id for chunk_id, _, _ in ranked]
    chunk_rows = await session.execute(
        select(ContextChunkORM).where(ContextChunkORM.id.in_(chunk_ids))
    )
    chunks_by_id = {row.id: row for row in chunk_rows.scalars().all()}
    context_ids = [context_id for _, context_id, _ in ranked]
    context_rows = await session.execute(
        select(ContextORM).where(ContextORM.id.in_(context_ids))
    )
    contexts_by_id = {row.id: row for row in context_rows.scalars().all()}

    matches: list[ContextSearchMatch] = []
    for chunk_id, context_id, rank in ranked:
        chunk_row = chunks_by_id.get(chunk_id)
        context_row = contexts_by_id.get(context_id)
        if chunk_row is None or context_row is None:
            continue
        fts_score = postgres_fts_rank_to_score(rank)
        matches.append(
            ContextSearchMatch(
                context=map_context_row(context_row),
                chunk=map_chunk_row(chunk_row),
                score=fts_score,
                fts_score=fts_score,
                vector_score=None,
                why_retrieved="Matched context chunk text with PostgreSQL full-text search.",
            )
        )
    return matches
