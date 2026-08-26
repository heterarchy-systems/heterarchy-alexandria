"""Phase 9 production graph closure benchmark contracts."""

from __future__ import annotations

import anyio
import httpx
from benchmarks.graph_production_closure_suite import (
    _run_case,
    summarize_graph_production,
)
from benchmarks.memory_eval_contracts import MemoryEvalCase, MemoryEvalQueryClass


def _case() -> MemoryEvalCase:
    return MemoryEvalCase(
        case_id="multi-hop-production-test",
        query="contract에서 seal까지 graph evidence chain",
        query_class=MemoryEvalQueryClass.MULTI_HOP_GRAPH,
        project="heterarchy-alexandria",
        include_scopes=("PROJECT", "GLOBAL"),
        include_lifecycle_statuses=(),
        expected_context_ids=("target-a", "target-b"),
        expected_titles=("Target A", "Target B"),
        forbidden_context_ids=(),
        forbidden_titles=(),
        required_graph_relations=("wikilink",),
        minimum_graph_distance=2,
        minimum_expected_matches=2,
        expected_abstention=False,
        rationale="Reviewed production closure truth.",
    )


def _search_response(strategy: str) -> httpx.Response:
    matches = [
        {
            "canonical_context_id": "target-a",
            "context": {"id": "obsidian:target-a", "title": "Target A"},
            "graph_evidence": (
                []
                if strategy == "HYBRID"
                else [{"relation": "wikilink", "distance": 2}]
            ),
        }
    ]
    if strategy == "AUTO":
        matches.append(
            {
                "canonical_context_id": "target-b",
                "context": {"id": "obsidian:target-b", "title": "Target B"},
                "graph_evidence": [{"relation": "wikilink", "distance": 2}],
            }
        )
    return httpx.Response(
        200,
        json={
            "effective_strategy": "HYBRID",
            "warnings": [],
            "matches": matches,
        },
    )


def _diagnostics_response(*, effective_strategy: str = "HYBRID") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "matches": [
                {
                    "context_id": "target-a",
                    "title": "Target A",
                    "graph_evidence_count": 0,
                },
                {
                    "context_id": "target-b",
                    "title": "Target B",
                    "graph_evidence_count": 2,
                },
            ],
            "trace": {
                "effective_strategy": effective_strategy,
                "graph_expansion_discovered_candidate_count": 40,
                "graph_expansion_selected_candidate_count": 3,
                "graph_expansion_hydrated_candidate_count": 2,
                "graph_expansion_filtered_candidate_count": 1,
                "graph_expansion_appended_candidate_count": 1,
                "graph_expansion_applied": True,
                "graph_expansion_degraded": False,
                "retrieval_plan": {"graph_depth": 2},
                "timings": {"graph_expansion_ms": 12.5, "total_ms": 25.0},
            },
        },
    )


def test_graph_production_case_combines_final_quality_and_operational_counters() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/memory/contexts/retrieval/search":
            strategy = request.read().decode()
            return _search_response("AUTO" if '"AUTO"' in strategy else "HYBRID")
        if request.url.path == "/operations/retrieval/explain":
            return _diagnostics_response()
        raise AssertionError(f"unexpected path: {request.url.path}")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://benchmark.test",
        ) as client:
            return await _run_case(client, _case(), 5)

    report = anyio.run(scenario)

    assert report.baseline.expected_recall_at_5 == 0.5
    assert report.production.expected_recall_at_5 == 1.0
    assert report.baseline.multi_hop_success == 0.0
    assert report.production.multi_hop_success == 1.0
    assert report.production.mean_reciprocal_rank == 1.0
    assert report.diagnostics.planned_graph_depth == 2
    assert report.diagnostics.discovered_candidate_count == 40
    assert report.diagnostics.selected_candidate_count == 3
    assert report.diagnostics.hydrated_candidate_count == 2
    assert report.diagnostics.filtered_candidate_count == 1
    assert report.diagnostics.appended_candidate_count == 1
    assert report.diagnostics.max_graph_evidence_count == 2
    assert report.final_ranking_matches_diagnostics is True

    summary = summarize_graph_production((report,), ())
    assert summary.expected_recall_at_5_delta == 0.5
    assert summary.multi_hop_success_rate_delta == 1.0
    assert summary.selector_retention_rate == 0.075
    assert summary.hydration_yield == 0.666667
    assert summary.final_append_yield == 0.5
    assert summary.ranking_parity_rate == 1.0
    assert summary.provenance_observed_case_count == 1
    assert summary.complete_path_provenance_rate == 1.0
    assert summary.quality_non_regression is True
    assert summary.closure_ready is True


def test_graph_production_summary_fails_closed_on_degraded_effective_strategy() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/memory/contexts/retrieval/search":
            strategy = request.read().decode()
            response = _search_response("AUTO" if '"AUTO"' in strategy else "HYBRID")
            if '"AUTO"' not in strategy:
                return response
            payload = response.json()
            payload["effective_strategy"] = "FTS_ONLY"
            return httpx.Response(200, json=payload)
        if request.url.path == "/operations/retrieval/explain":
            return _diagnostics_response(effective_strategy="FTS_ONLY")
        raise AssertionError(f"unexpected path: {request.url.path}")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://benchmark.test",
        ) as client:
            return await _run_case(client, _case(), 5)

    report = anyio.run(scenario)
    summary = summarize_graph_production((report,), ())

    assert summary.effective_strategy_mismatch_count == 1
    assert summary.closure_ready is False
