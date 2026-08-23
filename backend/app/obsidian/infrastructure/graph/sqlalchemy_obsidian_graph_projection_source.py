"""SQLAlchemy source adapter for the rebuildable Obsidian graph projection."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.domain.entities.obsidian_note import ObsidianEdge, ObsidianNote
from app.obsidian.domain.repositories.obsidian_graph_projection_source_repository import (
    IObsidianGraphProjectionSourceRepository,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianEdgeORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_index_mapping import (
    edge_from_model,
    note_from_model,
)


class SqlAlchemyObsidianGraphProjectionSource(IObsidianGraphProjectionSourceRepository):
    """Read graph projection source rows without modifying PostgreSQL or Markdown."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the read-only projection source adapter.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def list_projection_notes(self) -> tuple[ObsidianNote, ...]:
        """Return source notes ordered by stable note identity.

        Returns:
            Typed note rows from the Obsidian index.
        """
        rows = await self._session.scalars(
            select(ObsidianFileORM).order_by(ObsidianFileORM.note_id)
        )
        return tuple(note_from_model(model) for model in rows.all())

    async def list_projection_edges(self) -> tuple[ObsidianEdge, ...]:
        """Return source edges ordered by stable edge identity.

        Returns:
            Typed edge rows from the Obsidian graph cache.
        """
        rows = await self._session.scalars(
            select(ObsidianEdgeORM).order_by(ObsidianEdgeORM.edge_id)
        )
        return tuple(edge_from_model(model) for model in rows.all())
