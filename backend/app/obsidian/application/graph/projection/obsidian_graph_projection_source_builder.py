"""Build graph projection batches from the Obsidian index through explicit compute authority."""

from __future__ import annotations

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionSourceBuilderProtocol,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionSourceSnapshot,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_compute_provider import (
    IObsidianGraphProjectionComputeProvider,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_source_repository import (
    IObsidianGraphProjectionSourceRepository,
)


class ObsidianGraphProjectionSourceBuilder(
    ObsidianGraphProjectionSourceBuilderProtocol
):
    """Load typed graph source rows and delegate deterministic compute authority."""

    def __init__(
        self,
        source: IObsidianGraphProjectionSourceRepository,
        compute_provider: IObsidianGraphProjectionComputeProvider,
        batch_size: int = 500,
    ) -> None:
        """Create the projection source builder.

        Args:
            source: Read-only typed projection source.
            compute_provider: Explicit deterministic projection compute authority.
            batch_size: Maximum nodes and edges included in each batch.

        Raises:
            ValueError: When the requested batch size is not positive.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        self._source = source
        self._batch_size = batch_size
        self._compute_provider = compute_provider

    async def build(self) -> ObsidianGraphProjectionSourceSnapshot:
        """Load the current index state and return its computed projection snapshot.

        Returns:
            Immutable projection, bounded batches, and explicit source issues.
        """
        notes = await self._source.list_projection_notes()
        edges = await self._source.list_projection_edges()
        return self._compute_provider.compute(notes, edges, self._batch_size)
