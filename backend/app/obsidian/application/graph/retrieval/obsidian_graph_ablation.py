"""Deterministic bounded graph-depth ablation over one immutable projection snapshot."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
)

_MAX_ABLATION_DEPTH = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphAblationPath:
    """One shortest deterministic graph path discovered from a retrieval seed."""

    seed_note_id: str
    target_note_id: str
    distance: int
    node_ids: tuple[str, ...]
    relations: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphAblationMetrics:
    """Bounded-work counters for one graph-depth experiment."""

    depth: int
    seed_count: int
    discovered_note_count: int
    traversed_edge_count: int
    frontier_expansion_count: int
    truncated: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphAblationResult:
    """Pure graph expansion result used by Phase 9 evaluation and diagnostics."""

    discovered_note_ids: tuple[str, ...]
    paths: tuple[ObsidianGraphAblationPath, ...]
    metrics: ObsidianGraphAblationMetrics


@dataclass(frozen=True, slots=True)
class _AdjacentEdge:
    target_note_id: str
    relation: str
    edge_id: str


def ablate_graph_projection(
    projection: ObsidianGraphProjection,
    seed_note_ids: tuple[str, ...],
    depth: int,
    max_candidates: int = 200,
) -> ObsidianGraphAblationResult:
    """Expand one graph snapshot to depth 0, 1, or 2 with deterministic bounds.

    Args:
        projection: Immutable active graph projection snapshot.
        seed_note_ids: Canonical Context/note ids from primary retrieval.
        depth: Maximum undirected traversal depth for this experiment.
        max_candidates: Maximum non-seed nodes retained across the expansion.

    Returns:
        Deterministic shortest paths and bounded-work metrics for the requested depth.

    Raises:
        ValueError: If depth or candidate bounds are outside the Phase 9 contract.
    """
    if depth < 0 or depth > _MAX_ABLATION_DEPTH:
        raise ValueError("graph ablation depth must be 0..2")
    if max_candidates < 1 or max_candidates > 10_000:
        raise ValueError("graph ablation max_candidates must be 1..10000")
    seeds = tuple(dict.fromkeys(note_id for note_id in seed_note_ids if note_id))
    if not seeds or depth == 0:
        return _empty_result(depth=depth, seed_count=len(seeds))
    adjacency = _adjacency(projection.edges)
    seed_set = frozenset(seeds)
    visited = set(seeds)
    queue: deque[tuple[str, str, int, tuple[str, ...], tuple[str, ...]]] = deque(
        (seed, seed, 0, (seed,), ()) for seed in seeds
    )
    paths: list[ObsidianGraphAblationPath] = []
    traversed_edges = 0
    frontier_expansions = 0
    truncated = False
    while queue:
        seed, current, distance, node_path, relation_path = queue.popleft()
        if distance >= depth:
            continue
        frontier_expansions += 1
        for edge in adjacency.get(current, ()):
            traversed_edges += 1
            target = edge.target_note_id
            if target in visited:
                continue
            if len(paths) >= max_candidates:
                truncated = True
                queue.clear()
                break
            visited.add(target)
            next_nodes = (*node_path, target)
            next_relations = (*relation_path, edge.relation)
            next_distance = distance + 1
            if target not in seed_set:
                paths.append(
                    ObsidianGraphAblationPath(
                        seed_note_id=seed,
                        target_note_id=target,
                        distance=next_distance,
                        node_ids=next_nodes,
                        relations=next_relations,
                    )
                )
            if next_distance < depth:
                queue.append((seed, target, next_distance, next_nodes, next_relations))
    paths.sort(key=lambda item: (item.distance, item.target_note_id, item.seed_note_id))
    return ObsidianGraphAblationResult(
        discovered_note_ids=tuple(path.target_note_id for path in paths),
        paths=tuple(paths),
        metrics=ObsidianGraphAblationMetrics(
            depth=depth,
            seed_count=len(seeds),
            discovered_note_count=len(paths),
            traversed_edge_count=traversed_edges,
            frontier_expansion_count=frontier_expansions,
            truncated=truncated,
        ),
    )


def _empty_result(depth: int, seed_count: int) -> ObsidianGraphAblationResult:
    """Return a zero-expansion result for depth-zero or empty-seed experiments.

    Args:
        depth: Requested graph depth.
        seed_count: Number of unique non-empty seeds.

    Returns:
        Empty deterministic ablation result.
    """
    return ObsidianGraphAblationResult(
        discovered_note_ids=(),
        paths=(),
        metrics=ObsidianGraphAblationMetrics(
            depth=depth,
            seed_count=seed_count,
            discovered_note_count=0,
            traversed_edge_count=0,
            frontier_expansion_count=0,
            truncated=False,
        ),
    )


def _adjacency(
    edges: tuple[ObsidianGraphProjectionEdge, ...],
) -> dict[str, tuple[_AdjacentEdge, ...]]:
    """Build deterministic bidirectional adjacency from resolved projection edges.

    Args:
        edges: Active projection edges.

    Returns:
        Stable neighbor tuples keyed by canonical note id.
    """
    mutable: dict[str, list[_AdjacentEdge]] = {}
    for edge in edges:
        target = edge.target_note_id
        if target is None or target == edge.source_note_id:
            continue
        relation = edge.relation.value
        mutable.setdefault(edge.source_note_id, []).append(
            _AdjacentEdge(
                target_note_id=target, relation=relation, edge_id=edge.edge_id
            )
        )
        mutable.setdefault(target, []).append(
            _AdjacentEdge(
                target_note_id=edge.source_note_id,
                relation=relation,
                edge_id=edge.edge_id,
            )
        )
    return {
        source: tuple(
            sorted(
                neighbors,
                key=lambda item: (item.target_note_id, item.relation, item.edge_id),
            )
        )
        for source, neighbors in mutable.items()
    }
