"""Application service for Obsidian graph related-note reads."""

from __future__ import annotations

from app.obsidian.domain.entities.obsidian_note import ObsidianRelatedNote
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.infrastructure.markdown.paths import safe_relative_path
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianGraphUnavailableError,
    ObsidianNotFoundError,
)


class ObsidianGraphService:
    """Hydrate graph-provider relationships from the PostgreSQL note index."""

    def __init__(
        self,
        repository: IObsidianIndexQueryRepository,
        graph_repository: IObsidianGraphProjectionRepository | None,
    ) -> None:
        self._repository = repository
        self._graph_repository = graph_repository

    async def related_notes_by_path(
        self,
        relative_path: str,
        limit: int = 10,
    ) -> list[ObsidianRelatedNote]:
        """Return graph-related notes for one vault-relative path.

        Args:
            relative_path: Vault-relative Markdown path.
            limit: Maximum related-note count.
        Returns:
            Ranked graph-related notes.
        """
        graph_repository = self._require_graph_repository()
        safe_path = str(safe_relative_path(relative_path))
        note = await self._repository.get_by_path(safe_path)
        if note is None:
            raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
        return await self._hydrate_related(
            graph_repository=graph_repository,
            note_id=note.note_id,
            limit=limit,
        )

    async def related_notes(
        self,
        note_id: str,
        limit: int = 10,
    ) -> list[ObsidianRelatedNote]:
        """Return graph-related notes for one stable note id.

        Args:
            note_id: Stable source/target note id.
            limit: Maximum related-note count.
        Returns:
            Ranked graph-related notes.
        """
        graph_repository = self._require_graph_repository()
        note = await self._repository.get_by_id(note_id)
        if note is None:
            raise ObsidianNotFoundError(f"Obsidian note not found: {note_id}")
        return await self._hydrate_related(
            graph_repository=graph_repository,
            note_id=note_id,
            limit=limit,
        )

    def _require_graph_repository(self) -> IObsidianGraphProjectionRepository:
        if self._graph_repository is None:
            raise ObsidianGraphUnavailableError(
                "Obsidian graph read model is disabled; enable Neo4j and rebuild "
                "the projection before using related-note traversal"
            )
        return self._graph_repository

    async def _hydrate_related(
        self,
        graph_repository: IObsidianGraphProjectionRepository,
        note_id: str,
        limit: int,
    ) -> list[ObsidianRelatedNote]:
        graph_results = await graph_repository.related_notes(
            note_id=note_id,
            limit=limit,
        )
        hydrated: list[ObsidianRelatedNote] = []
        for result in graph_results:
            note = await self._repository.get_by_id(result.note_id)
            if note is None:
                continue
            hydrated.append(
                ObsidianRelatedNote(
                    note=note,
                    relation=result.relation,
                    source_kind=result.source_kind,
                    direction=result.direction.value,
                    score=result.score,
                    edge_id=result.edge_id,
                )
            )
        return hydrated
