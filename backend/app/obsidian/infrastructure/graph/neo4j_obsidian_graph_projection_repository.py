"""Async Neo4j adapter for the rebuildable Obsidian graph projection."""

from __future__ import annotations

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
    ObsidianGraphProjection,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionState,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.graph.neo4j_graph_projection_contracts import (
    Neo4jProjectionDriver,
)
from app.obsidian.infrastructure.graph.neo4j_graph_projection_operations import (
    _activate_projection,
    _delete_projection_run,
    _ensure_constraints,
    _read_context_evidence,
    _read_projection_state,
    _read_related_notes,
    _upsert_projection,
)


class Neo4jObsidianGraphProjectionRepository(IObsidianGraphProjectionRepository):
    """Project Obsidian graph snapshots into optional Neo4j state."""

    def __init__(
        self,
        driver: Neo4jProjectionDriver,
        database: str,
    ) -> None:
        """Create an adapter around one application-lifetime async driver.

        Args:
            driver: Shared async driver; sessions are never shared.
            database: Neo4j database selected for projection operations.
        """
        self._driver = driver
        self._database = database

    async def verify_connectivity(self) -> None:
        """Perform the explicit opt-in driver connectivity probe."""
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        """Await closure of the application-lifetime async driver."""
        await self._driver.close()

    async def start_rebuild(self, run_id: str, projection_version: int) -> None:
        """Prepare a clean run-scoped staging area.

        Args:
            run_id: Stable application-owned run id.
            projection_version: Projection contract version being written.
        """
        del projection_version
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(_ensure_constraints)
            await session.execute_write(_delete_projection_run, run_id)

    async def write_rebuild_batch(
        self,
        run_id: str,
        projection_version: int,
        batch: ObsidianGraphProjection,
    ) -> None:
        """Stage one bounded run-scoped batch without activating it.

        Args:
            run_id: Stable application-owned run id.
            projection_version: Projection contract version being written.
            batch: Bounded projection batch to stage.
        """
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(
                _upsert_projection,
                batch,
                run_id,
                projection_version,
            )

    async def complete_rebuild(
        self,
        run_id: str,
        projection_version: int,
        issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = (),
    ) -> None:
        """Atomically activate a staged run and delete superseded graph state.

        Args:
            run_id: Stable application-owned run id.
            projection_version: Projection contract version being activated.
        """
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(
                _activate_projection,
                run_id,
                projection_version,
                issue_counts,
            )

    async def abort_rebuild(self, run_id: str) -> None:
        """Delete nodes staged by a failed run.

        Args:
            run_id: Stable application-owned run id to clean up.
        """
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(_delete_projection_run, run_id)

    async def state(self) -> ObsidianGraphProjectionState:
        """Read active metadata and its deterministic typed snapshot.

        Returns:
            Active projection state or explicit never-built state.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.execute_read(_read_projection_state)
        if not isinstance(result, ObsidianGraphProjectionState):
            raise TypeError("Neo4j projection read returned an invalid result")
        return result

    async def related_notes(
        self,
        note_id: str,
        limit: int,
    ) -> tuple[ObsidianGraphRelatedNote, ...]:
        """Read ranked one-hop relations from the active projection run.

        Args:
            note_id: Stable note id whose neighbors should be expanded.
            limit: Maximum number of related notes to return.

        Returns:
            Ranked active-run relations mapped from Neo4j rows.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.execute_read(_read_related_notes, note_id, limit)
        if not isinstance(result, tuple):
            raise TypeError("Neo4j related-note read returned an invalid result")
        return result

    async def context_evidence(
        self,
        note_ids: tuple[str, ...],
    ) -> tuple[ObsidianGraphContextEvidence, ...]:
        """Read active-run graph evidence limited to recalled context ids.

        Args:
            note_ids: Recalled context ids allowed to appear in evidence.

        Returns:
            Typed active-run evidence whose endpoints are both allowed.
        """
        if not note_ids:
            return ()
        async with self._driver.session(database=self._database) as session:
            result = await session.execute_read(_read_context_evidence, note_ids)
        if not isinstance(result, tuple):
            raise TypeError("Neo4j context evidence read returned an invalid result")
        return result
