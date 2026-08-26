"""Memory Evaluation Suite corpus, metric, and runner contracts."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import anyio
import httpx
import pytest
from benchmarks.context_rag_benchmark_quality import load_golden_queries
from benchmarks.memory_eval_contracts import (
    MemoryEvalCase,
    MemoryEvalObservation,
    MemoryEvalQueryClass,
)
from benchmarks.memory_eval_corpus import (
    MemoryEvalCaseSchema,
    load_memory_eval_cases,
)
from benchmarks.memory_eval_metrics import (
    summarize_memory_eval_case,
    summarize_memory_eval_strategy,
)
from benchmarks.memory_evaluation_suite import (
    DEFAULT_STRATEGIES,
    STRATEGY_CHOICES,
    observe_memory_search,
)
from pydantic import ValidationError

BENCHMARK_ROOT = Path(__file__).resolve().parents[2] / "benchmarks"
MEMORY_CORPUS = BENCHMARK_ROOT / "memory_eval_cases.v1.json"
EXACT_CORPUS = BENCHMARK_ROOT / "golden_cases.exact_title.v1.json"
SEMANTIC_CORPUS = BENCHMARK_ROOT / "golden_cases.semantic.v1.json"


def _case(
    query_class: MemoryEvalQueryClass,
    expected_titles: tuple[str, ...] = ("Current",),
    forbidden_titles: tuple[str, ...] = (),
    minimum_expected_matches: int = 1,
    expected_abstention: bool = False,
    required_graph_relations: tuple[str, ...] = (),
    minimum_graph_distance: int = 0,
) -> MemoryEvalCase:
    """Create a compact metric-only truth fixture.

    Args:
        query_class: Memory ability under evaluation.
        expected_titles: Accepted result titles.
        forbidden_titles: Explicitly obsolete or incorrect result titles.
        minimum_expected_matches: Required distinct accepted memories.
        expected_abstention: Whether no retrieval is the correct result.
        required_graph_relations: Required graph evidence relation names.
        minimum_graph_distance: Minimum graph evidence distance required for success.

    Returns:
        Immutable memory-evaluation truth fixture.
    """
    return MemoryEvalCase(
        case_id=f"case-{query_class.value.lower()}",
        query="test query",
        query_class=query_class,
        project="heterarchy-alexandria",
        include_scopes=("PROJECT", "GLOBAL"),
        include_lifecycle_statuses=(),
        expected_context_ids=(),
        expected_titles=expected_titles,
        forbidden_context_ids=(),
        forbidden_titles=forbidden_titles,
        required_graph_relations=required_graph_relations,
        minimum_graph_distance=minimum_graph_distance,
        minimum_expected_matches=minimum_expected_matches,
        expected_abstention=expected_abstention,
        rationale="Reviewed deterministic test truth.",
    )


def _observation(
    titles: tuple[str, ...],
    graph_relations: tuple[str, ...] = (),
    graph_max_distance: int = 0,
    elapsed_ms: float = 10.0,
) -> MemoryEvalObservation:
    """Create one public-search observation without Context body data.

    Args:
        titles: Ranked titles returned by retrieval.
        graph_relations: Graph relation evidence names.
        graph_max_distance: Maximum graph evidence distance observed.
        elapsed_ms: Search wall-clock latency.

    Returns:
        Immutable benchmark observation.
    """
    return MemoryEvalObservation(
        elapsed_ms=elapsed_ms,
        effective_strategy="HYBRID",
        retrieved_context_ids=tuple("" for _ in titles),
        retrieved_titles=titles,
        retrieved_lifecycle_statuses=tuple(None for _ in titles),
        graph_relations=graph_relations,
        graph_max_distance=graph_max_distance,
        warning_count=0,
        response_bytes=256,
    )


def test_canonical_memory_eval_corpus_has_balanced_110_case_coverage() -> None:
    """Canonical corpus must keep ten reviewed cases for every required class."""
    cases = load_memory_eval_cases(MEMORY_CORPUS)
    counts = Counter(case.query_class for case in cases)

    assert len(cases) == 110
    assert set(counts) == set(MemoryEvalQueryClass)
    assert all(count == 10 for count in counts.values())
    assert len({case.case_id for case in cases}) == len(cases)
    assert len({case.query for case in cases}) == len(cases)


def test_memory_eval_corpus_preserves_existing_exact_and_semantic_golden_truth() -> (
    None
):
    """Phase 4 corpus must retain every pre-existing Golden Query and expected title."""
    cases = load_memory_eval_cases(MEMORY_CORPUS)
    by_query = {case.query: case for case in cases}
    previous = (
        *load_golden_queries(EXACT_CORPUS),
        *load_golden_queries(SEMANTIC_CORPUS),
    )

    assert len(previous) == 14
    for query in previous:
        migrated = by_query[query.query]
        assert migrated.project == query.project
        assert migrated.expected_titles == query.expected_titles
        assert set(query.expected_context_ids).issubset(migrated.expected_context_ids)
        assert len(migrated.expected_context_ids) == len(migrated.expected_titles)


def test_memory_eval_truth_rejects_ambiguous_abstention_and_graph_cases() -> None:
    """Strict corpus validation must reject contradictory or underspecified truth."""
    with pytest.raises(ValidationError):
        MemoryEvalCaseSchema.model_validate_json(
            b'{"case_id":"bad-abstention","query":"q","query_class":"UNKNOWN_ABSTENTION",'
            b'"project":null,"include_scopes":[],"include_lifecycle_statuses":[],'
            b'"expected_context_ids":[],"expected_titles":["Unexpected"],'
            b'"forbidden_context_ids":[],"forbidden_titles":[],'
            b'"required_graph_relations":[],"minimum_expected_matches":0,'
            b'"expected_abstention":true,"rationale":"invalid"}'
        )
    with pytest.raises(ValidationError):
        MemoryEvalCaseSchema.model_validate_json(
            b'{"case_id":"bad-graph","query":"q2","query_class":"MULTI_HOP_GRAPH",'
            b'"project":null,"include_scopes":[],"include_lifecycle_statuses":[],'
            b'"expected_context_ids":[],"expected_titles":["Target"],'
            b'"forbidden_context_ids":[],"forbidden_titles":[],'
            b'"required_graph_relations":[],"minimum_expected_matches":1,'
            b'"expected_abstention":false,"rationale":"invalid"}'
        )


def test_memory_eval_retrieval_metrics_include_recall_mrr_and_ndcg() -> None:
    """Rank-sensitive metrics should preserve the expected top-k semantics."""
    summary = summarize_memory_eval_case(
        _case(MemoryEvalQueryClass.SEMANTIC_PARAPHRASE),
        "HYBRID",
        [_observation(("Distractor", "Current"))],
        [],
    )

    assert summary.recall_at_1 == 0.0
    assert summary.recall_at_3 == 1.0
    assert summary.recall_at_5 == 1.0
    assert summary.mean_reciprocal_rank == 0.5
    assert summary.ndcg_at_5 == pytest.approx(0.63093, abs=1e-6)
    assert summary.wrong_memory_rate == 0.0


def test_temporal_and_supersession_metrics_penalize_obsolete_memory() -> None:
    """Current-state success must fail when explicitly obsolete memory leaks into top results."""
    temporal = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.TEMPORAL_CURRENT_STATE,
            forbidden_titles=("Obsolete",),
        ),
        "HYBRID",
        [_observation(("Current", "Obsolete"))],
        [],
    )
    supersession = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.SUPERSESSION,
            forbidden_titles=("Obsolete",),
        ),
        "HYBRID",
        [_observation(("Current", "Obsolete"))],
        [],
    )

    assert temporal.temporal_correctness == 0.0
    assert temporal.obsolete_memory_rate == 0.5
    assert temporal.historical_current_precision == 0.5
    assert temporal.wrong_memory_rate == 1.0
    assert supersession.superseded_memory_leakage_rate == 1.0
    assert supersession.historical_current_precision == 0.5


def test_conflict_abstention_graph_and_cross_language_metrics_are_explicit() -> None:
    """Memory-specific abilities should be measured independently from base recall."""
    preserved = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.CONFLICT_PRESERVATION,
            expected_titles=("View A", "View B"),
            minimum_expected_matches=2,
        ),
        "HYBRID",
        [_observation(("View A", "View B"))],
        [],
    )
    collapsed = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.CONFLICT_PRESERVATION,
            expected_titles=("View A", "View B"),
            minimum_expected_matches=2,
        ),
        "HYBRID",
        [_observation(("View A",))],
        [],
    )
    abstained = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.UNKNOWN_ABSTENTION,
            expected_titles=(),
            minimum_expected_matches=0,
            expected_abstention=True,
        ),
        "HYBRID",
        [_observation(())],
        [],
    )
    graph = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.MULTI_HOP_GRAPH,
            required_graph_relations=("wikilink",),
            minimum_graph_distance=2,
        ),
        "HYBRID",
        [_observation(("Current",), ("wikilink",), graph_max_distance=2)],
        [],
    )
    cross_language = summarize_memory_eval_case(
        _case(MemoryEvalQueryClass.CROSS_LANGUAGE),
        "HYBRID",
        [_observation(("Distractor", "Current"))],
        [],
    )

    assert preserved.conflict_collapse_rate == 0.0
    assert collapsed.conflict_collapse_rate == 1.0
    assert abstained.abstention_accuracy == 1.0
    assert abstained.wrong_memory_rate == 0.0
    assert graph.multi_hop_success_rate == 1.0
    assert cross_language.cross_language_success_rate == 1.0


def test_multi_hop_success_requires_reviewed_distance_and_expected_match_count() -> (
    None
):
    """Graph success must satisfy the corpus depth and distinct-target requirements."""
    case = _case(
        MemoryEvalQueryClass.MULTI_HOP_GRAPH,
        expected_titles=("Target A", "Target B"),
        minimum_expected_matches=2,
        required_graph_relations=("wikilink",),
        minimum_graph_distance=2,
    )
    shallow = summarize_memory_eval_case(
        case,
        "AUTO",
        [_observation(("Target A", "Target B"), ("wikilink",), graph_max_distance=1)],
        [],
    )
    incomplete = summarize_memory_eval_case(
        case,
        "AUTO",
        [_observation(("Target A",), ("wikilink",), graph_max_distance=2)],
        [],
    )

    assert shallow.multi_hop_success_rate == 0.0
    assert incomplete.multi_hop_success_rate == 0.0


def test_memory_function_and_wrong_premise_success_metrics_are_explicit() -> None:
    """Phase 6 functional recall and correction abilities should aggregate independently."""
    experiential = summarize_memory_eval_case(
        _case(MemoryEvalQueryClass.EXPERIENTIAL_RECALL),
        "HYBRID",
        [_observation(("Distractor", "Current"))],
        [],
    )
    procedural = summarize_memory_eval_case(
        _case(MemoryEvalQueryClass.PROCEDURAL_RECALL),
        "HYBRID",
        [_observation(("Current",))],
        [],
    )
    corrected = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.WRONG_PREMISE,
            forbidden_titles=("Obsolete",),
        ),
        "HYBRID",
        [_observation(("Current",))],
        [],
    )
    reinforced = summarize_memory_eval_case(
        _case(
            MemoryEvalQueryClass.WRONG_PREMISE,
            forbidden_titles=("Obsolete",),
        ),
        "HYBRID",
        [_observation(("Obsolete", "Current"))],
        [],
    )

    assert experiential.experiential_recall_success_rate == 1.0
    assert procedural.procedural_recall_success_rate == 1.0
    assert corrected.wrong_premise_correction_rate == 1.0
    assert reinforced.wrong_premise_correction_rate == 0.0


def test_strategy_summary_is_equal_case_weighted_and_tracks_instability() -> None:
    """Strategy aggregation must weight cases equally and count unstable rankings."""
    first = summarize_memory_eval_case(
        _case(MemoryEvalQueryClass.EXACT_LOOKUP),
        "HYBRID",
        [_observation(("Current",)), _observation(("Current",), elapsed_ms=20.0)],
        [],
    )
    second = summarize_memory_eval_case(
        _case(MemoryEvalQueryClass.SEMANTIC_PARAPHRASE),
        "HYBRID",
        [_observation(("Wrong",)), _observation(("Current",))],
        [],
    )

    aggregate = summarize_memory_eval_strategy("HYBRID", (first, second))

    assert aggregate.evaluated_cases == 2
    assert aggregate.recall_at_1 == 0.75
    assert aggregate.wrong_memory_rate == 0.25
    assert aggregate.unstable_case_count == 1


def test_memory_eval_runner_allows_auto_without_changing_fixed_defaults() -> None:
    """AUTO should be opt-in while historical fixed benchmark defaults stay stable."""
    assert "AUTO" in STRATEGY_CHOICES
    assert DEFAULT_STRATEGIES == ("FTS_ONLY", "VECTOR_ONLY", "HYBRID")


def test_read_only_runner_parses_graph_distance_without_context_body_dependency() -> (
    None
):
    """Runner observation should use bounded public metadata and graph evidence only."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/memory/contexts/retrieval/search"
        return httpx.Response(
            200,
            json={
                "effective_strategy": "HYBRID",
                "warnings": [],
                "matches": [
                    {
                        "canonical_context_id": "ctx-current",
                        "lifecycle_status": "ACTIVE",
                        "context": {
                            "id": "obsidian:ctx-current",
                            "title": "Current",
                            "content": "runner must not need this body",
                        },
                        "graph_evidence": [
                            {"relation": "wikilink", "distance": 2},
                            {"relation": "wikilink", "distance": 1},
                        ],
                    }
                ],
            },
        )

    async def scenario() -> MemoryEvalObservation:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://benchmark.test",
        ) as client:
            return await observe_memory_search(
                client,
                _case(
                    MemoryEvalQueryClass.MULTI_HOP_GRAPH,
                    required_graph_relations=("wikilink",),
                    minimum_graph_distance=2,
                ),
                "HYBRID",
                5,
            )

    observation = anyio.run(scenario)

    assert observation.retrieved_context_ids == ("ctx-current",)
    assert observation.retrieved_titles == ("Current",)
    assert observation.graph_relations == ("wikilink",)
    assert observation.graph_max_distance == 2
    assert observation.warning_count == 0
