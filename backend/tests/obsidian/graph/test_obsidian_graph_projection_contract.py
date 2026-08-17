"""Graph projection contract and in-memory repository behavior tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

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
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)


def _node(
    note_id: str,
    *,
    relative_path: str | None = None,
    title: str | None = None,
) -> ObsidianGraphProjectionNode:
    return ObsidianGraphProjectionNode(
        note_id=note_id,
        relative_path=relative_path or f"Alexandria/Contexts/{note_id}.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=title or note_id,
        status="active",
        project="heterarchy-alexandria",
    )


def _edge(
    edge_id: str,
    *,
    source_note_id: str,
    target_note_id: str,
) -> ObsidianGraphProjectionEdge:
    return ObsidianGraphProjectionEdge(
        edge_id=edge_id,
        source_note_id=source_note_id,
        source_path=f"Alexandria/Contexts/{source_note_id}.md",
        target_note_id=target_note_id,
        target_path=f"Alexandria/Contexts/{target_note_id}.md",
        relation=ObsidianRelationType.RELATED,
        confidence=1.0,
        source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
    )


def _projection(
    *,
    nodes: tuple[ObsidianGraphProjectionNode, ...] = (),
    edges: tuple[ObsidianGraphProjectionEdge, ...] = (),
) -> ObsidianGraphProjection:
    return ObsidianGraphProjection(nodes=nodes, edges=edges)


async def _activate(
    repository: FakeObsidianGraphProjectionRepository,
    projection: ObsidianGraphProjection,
    *,
    run_id: str,
) -> None:
    await repository.start_rebuild(run_id=run_id, projection_version=1)
    await repository.write_rebuild_batch(
        run_id=run_id,
        projection_version=1,
        batch=projection,
    )
    await repository.complete_rebuild(run_id=run_id, projection_version=1)


def test_projection_dtos_are_immutable() -> None:
    """Projection snapshots should not allow callers to mutate node data."""
    node = _node("note-a")

    with pytest.raises(FrozenInstanceError):
        setattr(node, "title", "changed")  # noqa: B010 - exercise runtime freezing


def test_in_memory_repository_implements_projection_repository_contract() -> None:
    """The in-memory fake should satisfy the same port as future adapters."""
    repository = FakeObsidianGraphProjectionRepository()

    assert isinstance(repository, IObsidianGraphProjectionRepository)


def test_in_memory_repository_returns_stable_ranked_one_hop_traversal() -> None:
    async def scenario() -> tuple[tuple[str, str, str], ...]:
        repository = FakeObsidianGraphProjectionRepository()
        await _activate(
            repository,
            _projection(
                nodes=(_node("note-a"), _node("note-b"), _node("note-c")),
                edges=(
                    _edge("edge-a-c", source_note_id="note-a", target_note_id="note-c"),
                    _edge("edge-b-a", source_note_id="note-b", target_note_id="note-a"),
                ),
            ),
            run_id="active-run",
        )
        related = await repository.related_notes(note_id="note-a", limit=10)
        return tuple(
            (item.note_id, item.direction.value, item.edge_id) for item in related
        )

    assert anyio.run(scenario) == (
        ("note-c", "outgoing", "edge-a-c"),
        ("note-b", "incoming", "edge-b-a"),
    )


def test_repeated_batches_are_idempotent_for_stable_projection_items() -> None:
    """Repeating one staged batch should not duplicate nodes or edges."""

    async def scenario() -> ObsidianGraphProjection:
        repository = FakeObsidianGraphProjectionRepository()
        projection = _projection(
            nodes=(_node("note-a"), _node("note-b")),
            edges=(
                _edge(
                    "edge-a-b",
                    source_note_id="note-a",
                    target_note_id="note-b",
                ),
            ),
        )

        await repository.start_rebuild(run_id="run-a", projection_version=1)
        await repository.write_rebuild_batch(
            run_id="run-a", projection_version=1, batch=projection
        )
        await repository.write_rebuild_batch(
            run_id="run-a", projection_version=1, batch=projection
        )
        await repository.complete_rebuild(run_id="run-a", projection_version=1)
        return await repository.snapshot()

    snapshot = anyio.run(scenario)

    assert tuple(node.note_id for node in snapshot.nodes) == ("note-a", "note-b")
    assert tuple(edge.edge_id for edge in snapshot.edges) == ("edge-a-b",)


def test_staged_batches_replace_items_with_the_same_stable_identity() -> None:
    """A later staged batch should replace an item with the same identity."""

    async def scenario() -> ObsidianGraphProjection:
        repository = FakeObsidianGraphProjectionRepository()
        await repository.start_rebuild(run_id="run-a", projection_version=1)
        await repository.write_rebuild_batch(
            run_id="run-a",
            projection_version=1,
            batch=_projection(nodes=(_node("note-a", title="Old title"),)),
        )
        await repository.write_rebuild_batch(
            run_id="run-a",
            projection_version=1,
            batch=_projection(nodes=(_node("note-a", title="Current title"),)),
        )
        await repository.complete_rebuild(run_id="run-a", projection_version=1)
        return await repository.snapshot()

    snapshot = anyio.run(scenario)

    assert tuple(node.title for node in snapshot.nodes) == ("Current title",)


def test_rebuild_replaces_stale_projection_state() -> None:
    """A full rebuild should remove nodes and edges absent from its payload."""

    async def scenario() -> tuple[ObsidianGraphProjection, ObsidianGraphProjection]:
        repository = FakeObsidianGraphProjectionRepository()
        await _activate(
            repository,
            _projection(
                nodes=(_node("stale-a"), _node("stale-b")),
                edges=(
                    _edge(
                        "stale-edge",
                        source_note_id="stale-a",
                        target_note_id="stale-b",
                    ),
                ),
            ),
            run_id="old-run",
        )
        current = _projection(
            nodes=(_node("current-a"), _node("current-b")),
            edges=(
                _edge(
                    "current-edge",
                    source_note_id="current-a",
                    target_note_id="current-b",
                ),
            ),
        )
        await _activate(repository, current, run_id="current-run")
        first = await repository.snapshot()
        await _activate(repository, current, run_id="current-run")
        return first, await repository.snapshot()

    first, second = anyio.run(scenario)

    assert first == second
    assert tuple(node.note_id for node in second.nodes) == ("current-a", "current-b")
    assert tuple(edge.edge_id for edge in second.edges) == ("current-edge",)


def test_snapshot_orders_projection_items_by_stable_identity() -> None:
    """Snapshots should be deterministic regardless of projection input order."""

    async def scenario() -> ObsidianGraphProjection:
        repository = FakeObsidianGraphProjectionRepository()
        await _activate(
            repository,
            _projection(
                nodes=(_node("note-b"), _node("note-a")),
                edges=(
                    _edge(
                        "edge-b",
                        source_note_id="note-b",
                        target_note_id="note-a",
                    ),
                    _edge(
                        "edge-a",
                        source_note_id="note-a",
                        target_note_id="note-b",
                    ),
                ),
            ),
            run_id="run-ordered",
        )
        return await repository.snapshot()

    snapshot = anyio.run(scenario)

    assert tuple(node.note_id for node in snapshot.nodes) == ("note-a", "note-b")
    assert tuple(edge.edge_id for edge in snapshot.edges) == ("edge-a", "edge-b")


def test_snapshot_is_isolated_from_later_repository_mutation() -> None:
    """A returned snapshot should remain stable after repository updates."""

    async def scenario() -> tuple[ObsidianGraphProjection, ObsidianGraphProjection]:
        repository = FakeObsidianGraphProjectionRepository()
        await _activate(
            repository, _projection(nodes=(_node("note-a"),)), run_id="run-a"
        )
        first = await repository.snapshot()
        await _activate(
            repository, _projection(nodes=(_node("note-b"),)), run_id="run-b"
        )
        return first, await repository.snapshot()

    first, second = anyio.run(scenario)

    assert tuple(node.note_id for node in first.nodes) == ("note-a",)
    assert tuple(node.note_id for node in second.nodes) == ("note-b",)


def test_aborted_staging_does_not_replace_active_projection() -> None:
    """A failed run cleanup must leave the previous active run consistent."""

    async def scenario() -> tuple[object, object]:
        repository = FakeObsidianGraphProjectionRepository()
        await _activate(
            repository, _projection(nodes=(_node("active"),)), run_id="active-run"
        )
        before = await repository.state()
        await repository.start_rebuild(run_id="failed-run", projection_version=1)
        await repository.write_rebuild_batch(
            run_id="failed-run",
            projection_version=1,
            batch=_projection(nodes=(_node("partial"),)),
        )
        await repository.abort_rebuild(run_id="failed-run")
        return before, await repository.state()

    before, after = anyio.run(scenario)

    assert after == before
    assert after.run_id == "active-run"
