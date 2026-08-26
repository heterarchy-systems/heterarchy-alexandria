"""Native Phase 7 reconciliation candidate evidence integration tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateComputeItem,
    ReconciliationCandidateComputePolicy,
)
from app.memory.infrastructure.providers.native_memory_reconciliation_candidate_compute_provider import (
    create_native_memory_reconciliation_candidate_compute_provider,
)

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def test_native_candidate_provider_emits_vector_graph_and_lineage_evidence() -> None:
    """Rust evidence should expose every hydrated deterministic feature without final policy."""
    provider = create_native_memory_reconciliation_candidate_compute_provider()
    items = (
        ReconciliationCandidateComputeItem(
            item_id="candidate-1",
            embedding=(1.0, 0.0),
            valid_from=NOW,
            blocking_keys=("source-pair:0",),
            graph_neighbors=("graph-shared", "graph-candidate"),
            lineage_ancestors=("ctx-old",),
        ),
        ReconciliationCandidateComputeItem(
            item_id="ctx-old",
            embedding=(1.0, 0.0),
            valid_from=NOW,
            blocking_keys=("source-pair:0",),
            graph_neighbors=("graph-shared", "graph-old"),
        ),
    )

    result = provider.discover(
        items,
        ReconciliationCandidateComputePolicy(
            vector_similarity_threshold=0.9,
            graph_similarity_threshold=0.3,
            max_block_size=2,
            max_candidates_per_item=1,
        ),
    )

    assert result.metrics.comparison_pairs == 1
    assert result.metrics.qualifying_pairs == 1
    assert result.metrics.retained_pairs == 1
    assert len(result.candidate_pairs) == 1
    pair = result.candidate_pairs[0]
    assert pair.left_id == "candidate-1"
    assert pair.right_id == "ctx-old"
    assert pair.vector_similarity == pytest.approx(1.0)
    assert pair.graph_similarity == pytest.approx(1.0 / 3.0)
    assert pair.lineage == "left_descends_from_right"
    assert pair.reasons == (
        "vector_similarity",
        "temporal_overlap",
        "graph_neighborhood",
        "lineage_structure",
    )
    assert pair.candidate_score == pytest.approx(1.0)
