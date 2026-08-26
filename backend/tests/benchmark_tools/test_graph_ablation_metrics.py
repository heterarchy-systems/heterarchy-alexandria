"""Pure graph-ablation metric regression tests."""

from __future__ import annotations

from benchmarks.graph_ablation_contracts import GraphAblationCaseObservation
from benchmarks.graph_ablation_metrics import (
    build_depth_observation,
    summarize_graph_ablation_depth,
)


def test_graph_ablation_depth_two_records_expected_target_lift_without_fake_relevance() -> (
    None
):
    depth_zero = build_depth_observation(
        depth=0,
        primary_ids=("seed",),
        expected_ids=("target",),
        discovered_ids=("seed",),
        minimum_expected_matches=1,
        traversal_request_count=0,
        traversal_truncated_count=0,
        graph_compute_ms=0.0,
    )
    depth_two = build_depth_observation(
        depth=2,
        primary_ids=("seed",),
        expected_ids=("target",),
        discovered_ids=("seed", "bridge", "target"),
        minimum_expected_matches=1,
        traversal_request_count=1,
        traversal_truncated_count=0,
        graph_compute_ms=2.5,
    )
    case = GraphAblationCaseObservation(
        case_id="multi-hop",
        query="seed to target",
        primary_context_ids=("seed",),
        expected_context_ids=("target",),
        search_ms=5.0,
        depths=(depth_zero, depth_two),
    )

    baseline = summarize_graph_ablation_depth((case,), 0)
    expanded = summarize_graph_ablation_depth((case,), 2)

    assert baseline.success_rate == 0.0
    assert baseline.expected_recall == 0.0
    assert expanded.success_rate == 1.0
    assert expanded.expected_recall == 1.0
    assert expanded.average_expanded_candidate_count == 2.0
    assert expanded.unlabeled_expansion_rate == 0.5
    assert expanded.graph_compute_p50_ms == 2.5


def test_graph_ablation_expansion_without_target_does_not_claim_quality_lift() -> None:
    observation = build_depth_observation(
        depth=2,
        primary_ids=("seed",),
        expected_ids=("target",),
        discovered_ids=("seed", "noise-a", "noise-b"),
        minimum_expected_matches=1,
        traversal_request_count=2,
        traversal_truncated_count=1,
        graph_compute_ms=4.0,
    )
    case = GraphAblationCaseObservation(
        case_id="no-lift",
        query="unhelpful graph",
        primary_context_ids=("seed",),
        expected_context_ids=("target",),
        search_ms=3.0,
        depths=(observation,),
    )

    summary = summarize_graph_ablation_depth((case,), 2)

    assert summary.success_rate == 0.0
    assert summary.expected_recall == 0.0
    assert summary.unlabeled_expansion_rate == 1.0
    assert summary.truncation_rate == 0.5
