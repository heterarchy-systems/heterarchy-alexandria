"""PostgreSQL/Rust graph projection repository regression tests."""

from typing import cast

import anyio
import pytest

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphContextSignalType,
    ObsidianGraphDirection,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_compute_provider import (
    IObsidianGraphProjectionComputeProvider,
)
from app.obsidian.infrastructure.graph.postgresql_obsidian_graph_projection_repository import (
    PostgreSqlObsidianGraphProjectionRepository,
)
from app.shared.infrastructure.database import Database


def _projection() -> ObsidianGraphProjection:
    return ObsidianGraphProjection(
        nodes=(
            ObsidianGraphProjectionNode(
                note_id="a",
                relative_path="Contexts/A.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="A",
                status="active",
                project=None,
            ),
            ObsidianGraphProjectionNode(
                note_id="b",
                relative_path="Memory/B.md",
                alexandria_type=AlexandriaNoteType.MEMORY_COMPACT,
                title="B",
                status="active",
                project=None,
            ),
            ObsidianGraphProjectionNode(
                note_id="c",
                relative_path="Contexts/C.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="C",
                status="active",
                project=None,
            ),
        ),
        edges=(
            ObsidianGraphProjectionEdge(
                edge_id="e-01",
                source_note_id="a",
                source_path="Contexts/A.md",
                target_note_id="b",
                target_path="Memory/B.md",
                relation=ObsidianRelationType.DERIVED_FROM,
                confidence=0.2,
                source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
            ),
            ObsidianGraphProjectionEdge(
                edge_id="e-02",
                source_note_id="a",
                source_path="Contexts/A.md",
                target_note_id="b",
                target_path="Memory/B.md",
                relation=ObsidianRelationType.RELATED,
                confidence=0.9,
                source_kind=ObsidianEdgeSourceKind.WIKILINK,
            ),
            ObsidianGraphProjectionEdge(
                edge_id="e-03",
                source_note_id="c",
                source_path="Contexts/C.md",
                target_note_id="a",
                target_path="Contexts/A.md",
                relation=ObsidianRelationType.SUPPORTS,
                confidence=0.9,
                source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
            ),
        ),
    )


def _repository() -> PostgreSqlObsidianGraphProjectionRepository:
    return PostgreSqlObsidianGraphProjectionRepository(
        database=cast(Database, object()),
        compute_provider=cast(IObsidianGraphProjectionComputeProvider, object()),
    )


def test_rebuild_activates_stable_projection_state() -> None:
    async def scenario() -> None:
        repository = _repository()
        projection = _projection()

        await repository.start_rebuild("run-1", 1)
        await repository.write_rebuild_batch("run-1", 1, projection)
        await repository.complete_rebuild("run-1", 1)

        state = await repository.state()
        assert state.initialized is True
        assert state.run_id == "run-1"
        assert state.projection_version == 1
        assert tuple(node.note_id for node in state.projection.nodes) == (
            "a",
            "b",
            "c",
        )
        assert tuple(edge.edge_id for edge in state.projection.edges) == (
            "e-01",
            "e-02",
            "e-03",
        )

    anyio.run(scenario)


def test_related_notes_preserve_weighting_direction_and_best_edge() -> None:
    async def scenario() -> None:
        repository = _repository()
        await repository.start_rebuild("run-1", 1)
        await repository.write_rebuild_batch("run-1", 1, _projection())
        await repository.complete_rebuild("run-1", 1)

        related = await repository.related_notes("a", 10)

        assert tuple(item.note_id for item in related) == ("c", "b")
        assert related[0].direction is ObsidianGraphDirection.INCOMING
        assert related[0].score == pytest.approx(1.6)
        assert related[1].edge_id == "e-02"
        assert related[1].direction is ObsidianGraphDirection.OUTGOING
        assert related[1].score == pytest.approx(1.5)

    anyio.run(scenario)


def test_context_evidence_preserves_signal_mapping_and_edge_order() -> None:
    async def scenario() -> None:
        repository = _repository()
        await repository.start_rebuild("run-1", 1)
        await repository.write_rebuild_batch("run-1", 1, _projection())
        await repository.complete_rebuild("run-1", 1)

        evidence = await repository.context_evidence(("a", "b"))

        assert tuple(item.edge_id for item in evidence) == ("e-01", "e-02")
        assert evidence[0].signal is ObsidianGraphContextSignalType.LINEAGE
        assert evidence[1].signal is ObsidianGraphContextSignalType.RESUME_PATH
        assert evidence[1].target_title == "B"

    anyio.run(scenario)
