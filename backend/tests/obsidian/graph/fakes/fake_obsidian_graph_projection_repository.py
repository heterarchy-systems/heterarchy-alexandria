"""Test fake for the Obsidian graph projection repository port."""

from __future__ import annotations

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionState,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphContextSignalType,
    ObsidianGraphDirection,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianRelationType,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)


class FakeObsidianGraphProjectionRepository(IObsidianGraphProjectionRepository):
    """Store an isolated graph projection in memory for contract tests."""

    def __init__(self) -> None:
        self._nodes: dict[str, ObsidianGraphProjectionNode] = {}
        self._edges: dict[str, ObsidianGraphProjectionEdge] = {}
        self._initialized = False
        self._run_id: str | None = None
        self._projection_version: int | None = None
        self._issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = ()
        self._staged_nodes: dict[str, dict[str, ObsidianGraphProjectionNode]] = {}
        self._staged_edges: dict[str, dict[str, ObsidianGraphProjectionEdge]] = {}

    async def start_rebuild(self, *, run_id: str, projection_version: int) -> None:
        """Prepare isolated in-memory staging maps for one rebuild.

        Args:
            run_id: Stable application-owned run id.
            projection_version: Projection contract version being written.
        """
        del projection_version
        self._staged_nodes[run_id] = {}
        self._staged_edges[run_id] = {}

    async def write_rebuild_batch(
        self,
        *,
        run_id: str,
        projection_version: int,
        batch: ObsidianGraphProjection,
    ) -> None:
        """Merge one batch into isolated staging state.

        Args:
            run_id: Stable application-owned run id.
            projection_version: Projection contract version being written.
            batch: Bounded nodes and edges to stage.
        """
        del projection_version
        self._staged_nodes[run_id].update((node.note_id, node) for node in batch.nodes)
        self._staged_edges[run_id].update((edge.edge_id, edge) for edge in batch.edges)

    async def complete_rebuild(
        self,
        *,
        run_id: str,
        projection_version: int,
        issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = (),
    ) -> None:
        """Activate a complete staged run in one in-memory assignment.

        Args:
            run_id: Stable application-owned run id.
            projection_version: Projection contract version being activated.
        """
        self._nodes = self._staged_nodes.pop(run_id)
        self._edges = self._staged_edges.pop(run_id)
        self._initialized = True
        self._run_id = run_id
        self._projection_version = projection_version
        self._issue_counts = tuple(issue_counts)

    async def abort_rebuild(self, *, run_id: str) -> None:
        """Discard isolated staging state for one failed run.

        Args:
            run_id: Stable application-owned run id to discard.
        """
        self._staged_nodes.pop(run_id, None)
        self._staged_edges.pop(run_id, None)

    async def state(self) -> ObsidianGraphProjectionState:
        """Return active metadata and stable identity-ordered tuples.

        Returns:
            Current active state detached from future writes.
        """
        nodes = tuple(self._nodes[node_id] for node_id in sorted(self._nodes))
        edges = tuple(self._edges[edge_id] for edge_id in sorted(self._edges))
        return ObsidianGraphProjectionState(
            initialized=self._initialized,
            run_id=self._run_id,
            projection_version=self._projection_version,
            projection=ObsidianGraphProjection(nodes=nodes, edges=edges),
            issue_total=sum(item.count for item in self._issue_counts),
            issue_counts=self._issue_counts,
        )

    async def related_notes(
        self,
        *,
        note_id: str,
        limit: int,
    ) -> tuple[ObsidianGraphRelatedNote, ...]:
        """Return deterministic one-hop neighbors from the active projection.

        Args:
            note_id: Stable note id whose neighbors should be expanded.
            limit: Maximum number of related notes to return.

        Returns:
            Ranked active-projection relations.
        """
        if not self._initialized:
            return ()
        results: dict[str, ObsidianGraphRelatedNote] = {}
        for edge in self._edges.values():
            if edge.source_note_id == note_id and edge.target_note_id in self._nodes:
                related_id = edge.target_note_id
                direction = ObsidianGraphDirection.OUTGOING
            elif edge.target_note_id == note_id and edge.source_note_id in self._nodes:
                related_id = edge.source_note_id
                direction = ObsidianGraphDirection.INCOMING
            else:
                continue
            if related_id is None:
                continue
            result = ObsidianGraphRelatedNote(
                note_id=related_id,
                edge_id=edge.edge_id,
                relation=edge.relation,
                source_kind=edge.source_kind,
                direction=direction,
                score=_relation_weight(edge.relation) + edge.confidence,
            )
            current = results.get(related_id)
            if current is None or (-result.score, result.edge_id) < (
                -current.score,
                current.edge_id,
            ):
                results[related_id] = result
        return tuple(
            sorted(
                results.values(),
                key=lambda item: (-item.score, item.edge_id, item.note_id),
            )[:limit]
        )

    async def context_evidence(
        self,
        *,
        note_ids: tuple[str, ...],
    ) -> tuple[ObsidianGraphContextEvidence, ...]:
        """Return stable active edges whose endpoints are both recalled.

        Args:
            note_ids: Recalled context ids allowed to appear in evidence.

        Returns:
            Stable evidence whose endpoints are both allowed.
        """
        allowed = frozenset(note_ids)
        if not self._initialized or not allowed:
            return ()
        results: list[ObsidianGraphContextEvidence] = []
        for edge in sorted(self._edges.values(), key=lambda item: item.edge_id):
            if (
                edge.target_note_id is None
                or edge.source_note_id not in allowed
                or edge.target_note_id not in allowed
            ):
                continue
            target = self._nodes.get(edge.target_note_id)
            if target is None:
                continue
            results.append(
                ObsidianGraphContextEvidence(
                    signal=_context_signal_type(
                        relation=edge.relation,
                        target_type=target.alexandria_type,
                    ),
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    target_note_id=target.note_id,
                    target_title=target.title,
                    relation=edge.relation,
                )
            )
        return tuple(results)


def _relation_weight(relation: ObsidianRelationType) -> float:
    return {
        ObsidianRelationType.DERIVED_FROM: 1.0,
        ObsidianRelationType.CITES: 0.9,
        ObsidianRelationType.SUPERSEDES: 0.8,
        ObsidianRelationType.PROMOTES_TO: 0.8,
        ObsidianRelationType.RELATED: 0.6,
        ObsidianRelationType.WIKILINK: 0.5,
        ObsidianRelationType.BLOCKS: 0.4,
        ObsidianRelationType.RESOLVES: 0.4,
        ObsidianRelationType.SUPPORTS: 0.7,
        ObsidianRelationType.EXTENDS: 0.7,
        ObsidianRelationType.CONTRADICTS: 0.4,
        ObsidianRelationType.DUPLICATES: 0.8,
        ObsidianRelationType.CONTAINS: 0.4,
    }[relation]


def _context_signal_type(
    *,
    relation: ObsidianRelationType,
    target_type: AlexandriaNoteType,
) -> ObsidianGraphContextSignalType:
    if relation is ObsidianRelationType.DUPLICATES:
        return ObsidianGraphContextSignalType.DUPLICATE_CANDIDATE
    if relation is ObsidianRelationType.SUPERSEDES:
        return ObsidianGraphContextSignalType.SUPERSEDES_CANDIDATE
    if relation in {
        ObsidianRelationType.BLOCKS,
        ObsidianRelationType.RESOLVES,
        ObsidianRelationType.CONTRADICTS,
    }:
        return ObsidianGraphContextSignalType.IMPACT_ANALYSIS
    if relation in {
        ObsidianRelationType.DERIVED_FROM,
        ObsidianRelationType.PROMOTES_TO,
        ObsidianRelationType.SUPPORTS,
        ObsidianRelationType.EXTENDS,
    }:
        return ObsidianGraphContextSignalType.LINEAGE
    if target_type in {
        AlexandriaNoteType.MEMORY_COMPACT,
        AlexandriaNoteType.JOB_PLAN,
        AlexandriaNoteType.IMPLEMENTATION_HISTORY,
    }:
        return ObsidianGraphContextSignalType.RESUME_PATH
    return ObsidianGraphContextSignalType.GRAPH_PROXIMITY
