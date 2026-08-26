"""Golden-corpus regression for the deterministic adaptive retrieval planner."""

from __future__ import annotations

from pathlib import Path

from benchmarks.adaptive_retrieval_planner_eval import (
    AdaptiveRetrievalPlannerCorpusSchema,
    evaluate_adaptive_retrieval_planner,
)

BENCHMARK_ROOT = Path(__file__).resolve().parents[2] / "benchmarks"
PLANNER_CORPUS = BENCHMARK_ROOT / "adaptive_retrieval_planner_cases.v1.json"


def test_adaptive_retrieval_planner_golden_corpus_is_strict_and_complete() -> None:
    """Planner profile v1 should keep its independent bilingual intent corpus exact."""
    corpus = AdaptiveRetrievalPlannerCorpusSchema.model_validate_json(
        PLANNER_CORPUS.read_bytes()
    )
    summary = evaluate_adaptive_retrieval_planner(PLANNER_CORPUS)

    assert corpus.schema_version == 1
    assert corpus.planner_profile == "adaptive-retrieval-v1"
    assert len(corpus.cases) == 35
    assert summary.total_cases == 35
    assert summary.passed_cases == 35
    assert summary.classification_accuracy == 1.0
    assert summary.failures == ()
