"""PostgreSQL-backed active Obsidian graph projection repository."""

from __future__ import annotations

from collections import Counter

from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionIssue,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionState,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_compute_provider import (
    IObsidianGraphProjectionComputeProvider,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_reads import (
    context_evidence,
    related_notes,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
)
from app.shared.infrastructure.database import Database

_PROJECTION_VERSION = 1


class PostgreSqlObsidianGraphProjectionRepository(IObsidianGraphProjectionRepository):
    """Own an app-lifetime projection cache sourced from PostgreSQL and Rust compute."""

    def __init__(
        self,
        database: Database,
        compute_provider: IObsidianGraphProjectionComputeProvider,
        batch_size: int = 500,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        self._database = database
        self._compute_provider = compute_provider
        self._batch_size = batch_size
        self._state: ObsidianGraphProjectionState | None = None
        self._staging_run_id: str | None = None
        self._staging_version: int | None = None
        self._staging_nodes: list[ObsidianGraphProjectionNode] = []
        self._staging_edges: list[ObsidianGraphProjectionEdge] = []

    async def start_rebuild(self, run_id: str, projection_version: int) -> None:
        if not run_id.strip():
            raise ValueError("run_id must not be blank")
        if projection_version <= 0:
            raise ValueError("projection_version must be positive")
        self._staging_run_id = run_id
        self._staging_version = projection_version
        self._staging_nodes = []
        self._staging_edges = []

    async def write_rebuild_batch(
        self,
        run_id: str,
        projection_version: int,
        batch: ObsidianGraphProjection,
    ) -> None:
        self._require_staging(run_id, projection_version)
        self._staging_nodes.extend(batch.nodes)
        self._staging_edges.extend(batch.edges)

    async def complete_rebuild(
        self,
        run_id: str,
        projection_version: int,
        issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = (),
    ) -> None:
        self._require_staging(run_id, projection_version)
        counts = tuple(issue_counts)
        self._state = ObsidianGraphProjectionState(
            initialized=True,
            run_id=run_id,
            projection_version=projection_version,
            projection=ObsidianGraphProjection(
                nodes=tuple(sorted(self._staging_nodes, key=lambda item: item.note_id)),
                edges=tuple(sorted(self._staging_edges, key=lambda item: item.edge_id)),
            ),
            issue_total=sum(item.count for item in counts),
            issue_counts=counts,
        )
        self._clear_staging()

    async def abort_rebuild(self, run_id: str) -> None:
        if self._staging_run_id == run_id:
            self._clear_staging()

    async def state(self) -> ObsidianGraphProjectionState:
        state = await self._ensure_state()
        return ObsidianGraphProjectionState(
            initialized=state.initialized,
            run_id=state.run_id,
            projection_version=state.projection_version,
            projection=ObsidianGraphProjection(
                nodes=state.projection.nodes,
                edges=state.projection.edges,
            ),
            issue_total=state.issue_total,
            issue_counts=state.issue_counts,
        )

    async def related_notes(
        self,
        note_id: str,
        limit: int,
    ) -> tuple[ObsidianGraphRelatedNote, ...]:
        return related_notes((await self._ensure_state()).projection, note_id, limit)

    async def context_evidence(
        self,
        note_ids: tuple[str, ...],
    ) -> tuple[ObsidianGraphContextEvidence, ...]:
        return context_evidence((await self._ensure_state()).projection, note_ids)

    async def _ensure_state(self) -> ObsidianGraphProjectionState:
        state = self._state
        if state is not None:
            return state
        session_factory = self._database.session_factory()
        async with session_factory() as session:
            builder = ObsidianGraphProjectionSourceBuilder(
                source=SqlAlchemyObsidianGraphProjectionSource(session),
                compute_provider=self._compute_provider,
                batch_size=self._batch_size,
            )
            snapshot = await builder.build()
        state = ObsidianGraphProjectionState(
            initialized=True,
            run_id="postgresql-current",
            projection_version=_PROJECTION_VERSION,
            projection=snapshot.projection,
            issue_total=len(snapshot.issues),
            issue_counts=_issue_counts(snapshot.issues),
        )
        self._state = state
        return state

    def _require_staging(self, run_id: str, projection_version: int) -> None:
        if (
            self._staging_run_id != run_id
            or self._staging_version != projection_version
        ):
            raise RuntimeError("graph projection rebuild is not active for this run")

    def _clear_staging(self) -> None:
        self._staging_run_id = None
        self._staging_version = None
        self._staging_nodes = []
        self._staging_edges = []


def _issue_counts(
    issues: tuple[ObsidianGraphProjectionIssue, ...],
) -> tuple[ObsidianGraphProjectionIssueCount, ...]:
    counts = Counter(issue.code for issue in issues)
    return tuple(
        ObsidianGraphProjectionIssueCount(code=code, count=count)
        for code, count in sorted(counts.items(), key=lambda item: item[0].value)
    )
