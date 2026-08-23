"""Contract tests for the Context RAG API benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from benchmarks.context_rag_api_benchmark import _search_payload
from benchmarks.context_rag_benchmark_contracts import (
    BenchmarkConfig,
    BenchmarkQuery,
    SearchObservation,
)
from benchmarks.context_rag_benchmark_quality import (
    load_golden_queries as _load_golden_queries,
    retrieved_context_ids as _retrieved_context_ids,
    retrieved_titles as _retrieved_titles,
    summarize_case as _summarize_case,
    summarize_strategy_quality as _summarize_strategy_quality,
)


def _observation(
    latency_ms: float,
    retrieved_context_ids: tuple[str, ...],
    retrieved_titles: tuple[str, ...] | None = None,
) -> SearchObservation:
    titles = retrieved_titles or tuple(
        f"Title {index}" for index in range(len(retrieved_context_ids))
    )
    return SearchObservation(
        elapsed_ms=latency_ms,
        status_code=200,
        effective_strategy="HYBRID",
        match_count=max(len(retrieved_context_ids), len(titles)),
        warning_count=0,
        graph_evidence_match_count=1,
        response_bytes=100,
        retrieved_context_ids=retrieved_context_ids,
        retrieved_titles=titles,
    )


def test_load_golden_queries_supports_context_ids_and_obsidian_titles(
    tmp_path: Path,
) -> None:
    """Golden cases should support both public Context ids and stable note titles."""
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "query": "  retrieval architecture  ",
                        "project": "  heterarchy-alexandria  ",
                        "expected_context_ids": ["context-a", "context-a"],
                        "expected_titles": ["Architecture Note", "Architecture Note"],
                    },
                    {
                        "query": "memory steward",
                        "expected_titles": ["Alexandria Memory Steward Contract"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _load_golden_queries(path) == (
        BenchmarkQuery(
            query="retrieval architecture",
            project="heterarchy-alexandria",
            expected_context_ids=("context-a",),
            expected_titles=("Architecture Note",),
        ),
        BenchmarkQuery(
            query="memory steward",
            expected_titles=("Alexandria Memory Steward Contract",),
        ),
    )


def test_load_golden_queries_requires_at_least_one_expected_identity(
    tmp_path: Path,
) -> None:
    """A golden query without an accepted id or title is not evaluable."""
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps({"schema_version": 1, "cases": [{"query": "missing"}]}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="must define expected_context_ids or expected_titles"
    ):
        _load_golden_queries(path)


def test_search_payload_prefers_case_project_over_global_fallback() -> None:
    """Each Golden Query may select the project scope required by its canonical note."""
    config = BenchmarkConfig(
        base_url="http://127.0.0.1:8000",
        queries=(),
        strategies=("FTS_ONLY",),
        project="global-fallback",
        limit=5,
        warmups=0,
        repetitions=1,
        timeout_seconds=5.0,
        token_env="TOKEN",
        output_path=None,
        golden_cases_path=None,
    )

    payload = _search_payload(
        config,
        BenchmarkQuery(query="target", project="case-project"),
        "FTS_ONLY",
    )

    assert payload["project"] == "case-project"


def test_load_golden_queries_rejects_duplicate_queries(tmp_path: Path) -> None:
    """A query must have one unambiguous expected result set."""
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {"query": "same", "expected_context_ids": ["context-a"]},
                    {"query": "same", "expected_titles": ["Context B"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate golden query"):
        _load_golden_queries(path)


def test_retrieved_identity_extractors_preserve_response_order() -> None:
    """Quality scoring should retain canonical ids and titles in rank order."""
    matches: list[object] = [
        {
            "canonical_context_id": "canonical-a",
            "context": {"id": "projection-a", "title": "Title A"},
        },
        {"context": {"id": "fallback-b", "title": "Title B"}},
        {"canonical_context_id": None, "context": None},
    ]

    assert _retrieved_context_ids(matches) == ("canonical-a", "fallback-b")
    assert _retrieved_titles(matches) == ("Title A", "Title B")


def test_case_summary_records_id_quality_latency_and_ranking_instability() -> None:
    """One case should combine latency evidence with repeated id ranking quality."""
    summary = _summarize_case(
        BenchmarkQuery(query="find target", expected_context_ids=("target",)),
        "HYBRID",
        [
            _observation(10.0, ("target", "noise")),
            _observation(20.0, ("noise", "target")),
        ],
        [],
    )

    assert summary.latency_p50_ms == 10.0
    assert summary.latency_p95_ms == 20.0
    assert summary.recall_at_1 == 0.5
    assert summary.recall_at_3 == 1.0
    assert summary.mean_reciprocal_rank == 0.75
    assert summary.ranking_stable is False
    assert summary.retrieved_context_id_variants == (
        ("noise", "target"),
        ("target", "noise"),
    )


def test_case_summary_scores_obsidian_title_identity() -> None:
    """Obsidian results should be evaluable even when public Context ids are projected."""
    summary = _summarize_case(
        BenchmarkQuery(
            query="memory steward",
            expected_titles=("Alexandria Memory Steward Contract",),
        ),
        "VECTOR_ONLY",
        [
            _observation(
                12.0,
                ("projection-a", "projection-b"),
                ("Noise", "Alexandria Memory Steward Contract"),
            )
        ],
        [],
    )

    assert summary.recall_at_1 == 0.0
    assert summary.recall_at_3 == 1.0
    assert summary.mean_reciprocal_rank == 0.5
    assert summary.expected_titles == ("Alexandria Memory Steward Contract",)


def test_strategy_quality_equal_weights_evaluable_queries() -> None:
    """Repeated samples must not cause one query to outweigh another query."""
    first = _summarize_case(
        BenchmarkQuery(query="first", expected_context_ids=("target",)),
        "HYBRID",
        [_observation(10.0, ("target",))],
        [],
    )
    second = _summarize_case(
        BenchmarkQuery(query="second", expected_titles=("Target",)),
        "HYBRID",
        [_observation(10.0, ("noise",), ("Noise",)) for _ in range(5)],
        [],
    )

    summary = _summarize_strategy_quality("HYBRID", (first, second))

    assert summary.evaluated_cases == 2
    assert summary.recall_at_1 == 0.5
    assert summary.recall_at_3 == 0.5
    assert summary.mean_reciprocal_rank == 0.5
    assert summary.unstable_case_count == 0


def test_repository_golden_case_example_is_valid() -> None:
    """The committed example should remain executable documentation."""
    example_path = Path(__file__).parents[2] / "benchmarks/golden_cases.example.json"

    queries = _load_golden_queries(example_path)

    assert len(queries) == 2
    assert queries[0].expected_titles == ("Expected Obsidian Note Title",)
    assert queries[1].expected_context_ids == ("replace-with-stable-context-id",)


def test_repository_semantic_golden_cases_are_versioned_and_non_title_queries() -> None:
    """The semantic corpus should exercise paraphrased recall, not title echoing."""
    corpus_path = Path(__file__).parents[2] / "benchmarks/golden_cases.semantic.v1.json"

    queries = _load_golden_queries(corpus_path)

    assert len(queries) == 10
    assert {query.project for query in queries} == {"heterarchy-alexandria"}
    assert all(query.expected_titles for query in queries)
    assert all(query.query not in query.expected_titles for query in queries)


def test_repository_exact_title_golden_cases_are_versioned() -> None:
    """Exact-title recall should remain a separate versioned regression corpus."""
    corpus_path = (
        Path(__file__).parents[2] / "benchmarks/golden_cases.exact_title.v1.json"
    )

    queries = _load_golden_queries(corpus_path)

    assert len(queries) == 4
    assert all(query.expected_titles for query in queries)
    assert all(query.query in query.expected_titles for query in queries)
