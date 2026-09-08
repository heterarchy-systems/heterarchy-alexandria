"""Shared graph-status boundary fakes for operational readiness tests."""

from __future__ import annotations

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)


class HealthyGraphProjectionService:
    """Deterministic graph status boundary used by readiness unit tests."""

    async def status(self) -> ObsidianGraphProjectionStatusReport:
        """Return current ready graph projection evidence."""
        return ObsidianGraphProjectionStatusReport(
            status="ready",
            graph_read_model="postgresql",
            enabled=True,
            node_count=3,
            edge_count=2,
            run_id="test-graph-run",
            projection_version=1,
        )
