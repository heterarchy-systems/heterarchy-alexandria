"""Pure aggregation helpers for graph retrieval ablation evidence."""

from __future__ import annotations

from collections.abc import Sequence

from benchmarks.graph_ablation_contracts import (
    GraphAblationCaseObservation,
    GraphAblationDepthObservation,
    GraphAblationDepthSummary,
)


def summarize_graph_ablation_depth(
    cases: Sequence[GraphAblationCaseObservation],
    depth: int,
) -> GraphAblationDepthSummary:
    """Aggregate one graph depth across all evaluated multi-hop cases.

    Args:
        cases: Case-level ablation observations.
        depth: Graph depth being summarized.

    Returns:
        Aggregate quality, expansion, truncation, and compute evidence.

    Raises:
        ValueError: If no case contains the requested depth.
    """
    observations = tuple(_depth(case, depth) for case in cases)
    if not observations:
        raise ValueError("GRAPH_ABLATION_EMPTY: no observations to summarize")
    total_expected = sum(item.expected_total for item in observations)
    total_hits = sum(item.expected_hit_count for item in observations)
    total_expanded = sum(item.expanded_candidate_count for item in observations)
    total_unlabeled = sum(item.unlabeled_expansion_count for item in observations)
    total_requests = sum(item.traversal_request_count for item in observations)
    total_truncated = sum(item.traversal_truncated_count for item in observations)
    latencies = sorted(item.graph_compute_ms for item in observations)
    return GraphAblationDepthSummary(
        depth=depth,
        case_count=len(observations),
        success_rate=sum(item.success for item in observations) / len(observations),
        expected_recall=(total_hits / total_expected if total_expected else 0.0),
        average_candidate_count=(
            sum(item.candidate_count for item in observations) / len(observations)
        ),
        average_expanded_candidate_count=(total_expanded / len(observations)),
        unlabeled_expansion_rate=(
            total_unlabeled / total_expanded if total_expanded else 0.0
        ),
        truncation_rate=(total_truncated / total_requests if total_requests else 0.0),
        graph_compute_p50_ms=_percentile(latencies, 0.50),
        graph_compute_p95_ms=_percentile(latencies, 0.95),
    )


def build_depth_observation(
    depth: int,
    primary_ids: Sequence[str],
    expected_ids: Sequence[str],
    discovered_ids: Sequence[str],
    minimum_expected_matches: int,
    traversal_request_count: int,
    traversal_truncated_count: int,
    graph_compute_ms: float,
) -> GraphAblationDepthObservation:
    """Build one truth-aware depth observation without inventing relevance labels.

    Args:
        depth: Graph expansion depth.
        primary_ids: Primary retrieval seed identities.
        expected_ids: Corpus-labeled expected identities.
        discovered_ids: Primary plus graph-discovered identities.
        minimum_expected_matches: Minimum distinct expected hits required for success.
        traversal_request_count: Native traversal request count for this case.
        traversal_truncated_count: Native requests that hit a traversal bound.
        graph_compute_ms: Native graph traversal wall time.

    Returns:
        One deterministic depth observation.
    """
    primary = set(primary_ids)
    expected = set(expected_ids)
    discovered = set(discovered_ids)
    hits = expected & discovered
    expanded = discovered - primary
    unlabeled = expanded - expected
    return GraphAblationDepthObservation(
        depth=depth,
        expected_hit_count=len(hits),
        expected_total=len(expected),
        success=len(hits) >= minimum_expected_matches,
        candidate_count=len(discovered),
        expanded_candidate_count=len(expanded),
        unlabeled_expansion_count=len(unlabeled),
        traversal_request_count=traversal_request_count,
        traversal_truncated_count=traversal_truncated_count,
        graph_compute_ms=graph_compute_ms,
    )


def _depth(
    case: GraphAblationCaseObservation,
    depth: int,
) -> GraphAblationDepthObservation:
    """Return one requested depth observation from a case.

    Args:
        case: Case-level observation.
        depth: Requested graph depth.

    Returns:
        Matching depth observation.

    Raises:
        ValueError: If the case does not contain the requested depth.
    """
    for observation in case.depths:
        if observation.depth == depth:
            return observation
    raise ValueError(f"GRAPH_ABLATION_DEPTH_MISSING: {case.case_id} depth={depth}")


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Return a deterministic nearest-rank percentile for non-empty values.

    Args:
        values: Sorted latency values.
        percentile: Requested percentile between zero and one.

    Returns:
        Nearest-rank percentile, or zero for an empty sequence.
    """
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * percentile)))
    return values[index]
