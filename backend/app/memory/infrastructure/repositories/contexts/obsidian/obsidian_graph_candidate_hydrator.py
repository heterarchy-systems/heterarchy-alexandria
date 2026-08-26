"""PostgreSQL hydration adapter for graph-discovered Obsidian Context candidates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.memory.domain.contracts.context_recall_contracts import ContextRecallFilter
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_hydrator import (
    ContextGraphHydratedCandidate,
    IContextGraphCandidateHydrator,
)
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_context_mapping import (
    chunk_record_from_obsidian_row,
    context_record_from_obsidian_row,
    matches_context_filters,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_recall_policy import (
    _obsidian_scope_recall_clause,
    _recall_visibility_conditions,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)

_MAX_GRAPH_HYDRATION_IDS = 8


class ObsidianGraphCandidateHydrator(IContextGraphCandidateHydrator):
    """Restore graph-selected notes and representative indexed chunks."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the request-scoped graph candidate hydrator.

        Args:
            session: Active request-scoped PostgreSQL session.
        """
        self._session = session

    async def hydrate(
        self,
        note_ids: tuple[str, ...],
        recall_filter: ContextRecallFilter,
    ) -> tuple[ContextGraphHydratedCandidate, ...]:
        """Hydrate eligible candidates with two bounded SQL queries.

        Args:
            note_ids: Selected graph note identities in desired order.
            recall_filter: Existing recall scope/lifecycle boundary.

        Returns:
            Eligible Context/chunk pairs in original selected order.

        Raises:
            ValueError: If caller exceeds the bounded graph hydration contract.
        """
        unique_ids = tuple(dict.fromkeys(note_ids))
        if not unique_ids:
            return ()
        if len(unique_ids) > _MAX_GRAPH_HYDRATION_IDS:
            raise ValueError(
                f"GRAPH_CANDIDATE_HYDRATION_LIMIT_EXCEEDED: max {_MAX_GRAPH_HYDRATION_IDS}"
            )
        scope_filter = recall_filter.scope_identity
        obsidian_table = ObsidianFileORM.__table__
        note_statement = (
            select(ObsidianFileORM)
            .where(
                ObsidianFileORM.note_id.in_(unique_ids),
                *_recall_visibility_conditions(recall_filter.lifecycle_statuses),
            )
            .where(
                _obsidian_scope_recall_clause(
                    obsidian_table.c.frontmatter_json,
                    obsidian_table.c.project,
                    scope_filter,
                )
            )
        )
        notes = {
            note.note_id: note
            for note in (
                await self._session.scalars(
                    note_statement,
                    scope_filter.sql_parameters(),
                )
            ).all()
        }
        if not notes:
            return ()
        chunk_statement = (
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
            .where(ObsidianChunkORM.note_id.in_(tuple(notes)))
            .order_by(
                ObsidianChunkORM.note_id.asc(), ObsidianChunkORM.chunk_index.asc()
            )
        )
        first_chunks: dict[str, ObsidianChunkORM] = {}
        for chunk in (await self._session.scalars(chunk_statement)).all():
            if chunk.text.strip():
                first_chunks.setdefault(chunk.note_id, chunk)
        hydrated: list[ContextGraphHydratedCandidate] = []
        for note_id in unique_ids:
            note = notes.get(note_id)
            chunk = first_chunks.get(note_id)
            if note is None or chunk is None:
                continue
            context = context_record_from_obsidian_row(note)
            if not matches_context_filters(
                note,
                context,
                recall_filter.kind,
                scope_filter,
                project=scope_filter.project,
                include_lifecycle_statuses=recall_filter.lifecycle_statuses,
            ):
                continue
            hydrated.append(
                ContextGraphHydratedCandidate(
                    note_id=note_id,
                    context=context,
                    chunk=chunk_record_from_obsidian_row(chunk, title=note.title),
                )
            )
        return tuple(hydrated)
