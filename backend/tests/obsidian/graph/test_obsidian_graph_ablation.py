"""Phase 9 bounded graph-depth ablation contracts."""

from __future__ import annotations

import pytest

from app.obsidian.application.graph.retrieval.obsidian_graph_ablation import (
    ablate_graph_projection,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)


def _edge(
    source: str,
    target: str | None,
    relation: ObsidianRelationType = ObsidianRelationType.WIKILINK,
) -> ObsidianGraphProjectionEdge:
    return ObsidianGraphProjectionEdge(
        edge_id=f"{source}:{relation.value}:{target}",
        source_note_id=source,
        source_path=f"Contexts/{source}.md",
        target_note_id=target,
        target_path=f"Contexts/{target or 'missing'}.md",
        relation=relation,
        confidence=1.0,
        source_kind=ObsidianEdgeSourceKind.WIKILINK,
    )


def _projection() -> ObsidianGraphProjection:
    return ObsidianGraphProjection(
        edges=(
            _edge("a", "b", ObsidianRelationType.CONTAINS),
            _edge("a", "e", ObsidianRelationType.RELATED),
            _edge("b", "c", ObsidianRelationType.WIKILINK),
            _edge("c", "d", ObsidianRelationType.EXTENDS),
            _edge("c", "a", ObsidianRelationType.RELATED),
            _edge("a", None, ObsidianRelationType.WIKILINK),
        )
    )


def test_depth_zero_disables_graph_expansion_without_work() -> None:
    """Depth zero must preserve the no-graph ablation baseline exactly."""
    result = ablate_graph_projection(_projection(), ("a",), depth=0)

    assert result.discovered_note_ids == ()
    assert result.paths == ()
    assert result.metrics.depth == 0
    assert result.metrics.seed_count == 1
    assert result.metrics.traversed_edge_count == 0
    assert result.metrics.frontier_expansion_count == 0
    assert result.metrics.truncated is False


def test_depth_one_returns_only_resolved_direct_neighbors_deterministically() -> None:
    """One-hop ablation must exclude unresolved targets, cycles, and deeper nodes."""
    result = ablate_graph_projection(_projection(), ("a",), depth=1)

    assert result.discovered_note_ids == ("b", "c", "e")
    assert [(path.target_note_id, path.distance) for path in result.paths] == [
        ("b", 1),
        ("c", 1),
        ("e", 1),
    ]
    assert all(path.seed_note_id == "a" for path in result.paths)
    assert result.metrics.discovered_note_count == 3
    assert result.metrics.truncated is False


def test_depth_two_adds_shortest_two_hop_candidate_without_revisiting_cycle() -> None:
    """Two-hop ablation should add shortest unseen candidates exactly once."""
    result = ablate_graph_projection(_projection(), ("a",), depth=2)

    assert result.discovered_note_ids == ("b", "c", "e", "d")
    path_d = next(path for path in result.paths if path.target_note_id == "d")
    assert path_d.distance == 2
    assert path_d.node_ids == ("a", "c", "d")
    assert path_d.relations == ("related", "extends")
    assert len(result.discovered_note_ids) == len(set(result.discovered_note_ids))
    assert result.metrics.frontier_expansion_count > 1


def test_multiple_seeds_keep_shortest_global_discovery_and_seed_identity() -> None:
    """Multi-seed BFS should retain the first deterministic shortest path per target."""
    result = ablate_graph_projection(_projection(), ("a", "d"), depth=2)

    assert "c" in result.discovered_note_ids
    path_c = next(path for path in result.paths if path.target_note_id == "c")
    assert path_c.distance == 1
    assert path_c.seed_note_id == "a"
    assert result.metrics.seed_count == 2


def test_candidate_bound_truncates_deterministically() -> None:
    """Ablation must stop at the explicit candidate bound without unbounded expansion."""
    result = ablate_graph_projection(_projection(), ("a",), depth=2, max_candidates=2)

    assert result.discovered_note_ids == ("b", "c")
    assert result.metrics.discovered_note_count == 2
    assert result.metrics.truncated is True


@pytest.mark.parametrize("depth", [-1, 3])
def test_invalid_depth_fails_closed(depth: int) -> None:
    """Phase 9 experimental graph depth is intentionally bounded to zero through two."""
    with pytest.raises(ValueError, match=r"depth must be 0\.\.2"):
        ablate_graph_projection(_projection(), ("a",), depth=depth)
