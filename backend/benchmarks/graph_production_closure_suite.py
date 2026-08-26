"""Phase 9 production-path closure benchmark for AUTO graph retrieval."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import httpx
import orjson

from benchmarks.benchmark_statistics import LatencySummary, summarize_latencies
from benchmarks.memory_eval_contracts import (
    MemoryEvalCase,
    MemoryEvalObservation,
    MemoryEvalQueryClass,
)
from benchmarks.memory_eval_corpus import load_memory_eval_cases
from benchmarks.memory_eval_metrics import summarize_memory_eval_case
from benchmarks.memory_evaluation_suite import (
    RETRIEVAL_KERNEL_AUTHORITY_HEADER,
    observe_memory_search,
)

DIAGNOSTICS_PATH = "/operations/retrieval/explain"
RAG_STATUS_PATH = "/memory/contexts/rag/status"
READINESS_PATH = "/operations/readiness"
DEFAULT_TOKEN_ENV = "ALEXANDRIA_BENCHMARK_BEARER_TOKEN"
DEFAULT_CORPUS_PATH = Path(__file__).with_name("memory_eval_cases.v1.json")
_BASELINE_STRATEGY = "HYBRID"
_PRODUCTION_STRATEGY = "AUTO"
_EXPECTED_GRAPH_DEPTH = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class _GraphClosureConfig:
    """Validated configuration for one production graph closure run."""

    base_url: str
    corpus_path: Path
    cases: tuple[MemoryEvalCase, ...]
    limit: int
    timeout_seconds: float
    token_env: str
    output_path: Path | None


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphFinalQuality:
    """Truth-aware final top-k quality for one production-path execution."""

    effective_strategy: str | None
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    expected_recall_at_1: float
    expected_recall_at_3: float
    expected_recall_at_5: float
    mean_reciprocal_rank: float
    ndcg_at_5: float
    multi_hop_success: float
    latency_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphExpansionDiagnostics:
    """Bounded operational evidence emitted by the normal explained search path."""

    effective_strategy: str
    planned_graph_depth: int | None
    discovered_candidate_count: int
    selected_candidate_count: int
    hydrated_candidate_count: int
    filtered_candidate_count: int
    appended_candidate_count: int
    expansion_applied: bool
    expansion_degraded: bool
    graph_expansion_ms: float
    total_ms: float
    request_elapsed_ms: float
    final_titles: tuple[str, ...]
    max_graph_evidence_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphProductionCaseReport:
    """Baseline and AUTO production evidence for one reviewed graph truth case."""

    case_id: str
    query: str
    baseline: GraphFinalQuality
    production: GraphFinalQuality
    diagnostics: GraphExpansionDiagnostics
    final_ranking_matches_diagnostics: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphProductionSummary:
    """Equal-case quality and operational summary for Phase 9 closure."""

    case_count: int
    baseline_hit_at_5: float
    production_hit_at_5: float
    baseline_expected_recall_at_5: float
    production_expected_recall_at_5: float
    expected_recall_at_5_delta: float
    baseline_mean_reciprocal_rank: float
    production_mean_reciprocal_rank: float
    mean_reciprocal_rank_delta: float
    baseline_multi_hop_success_rate: float
    production_multi_hop_success_rate: float
    multi_hop_success_rate_delta: float
    baseline_search_latency: LatencySummary
    production_search_latency: LatencySummary
    graph_expansion_latency: LatencySummary
    explained_total_latency: LatencySummary
    average_discovered_candidate_count: float
    average_selected_candidate_count: float
    average_hydrated_candidate_count: float
    average_filtered_candidate_count: float
    average_appended_candidate_count: float
    selector_retention_rate: float
    hydration_yield: float
    final_append_yield: float
    ranking_parity_rate: float
    provenance_observed_case_count: int
    complete_path_provenance_rate: float
    graph_depth_mismatch_count: int
    degraded_case_count: int
    effective_strategy_mismatch_count: int
    quality_non_regression: bool
    closure_ready: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphProductionEnvironment:
    """Runtime evidence recorded beside one Phase 9 closure report."""

    measured_at: str
    base_url: str
    corpus_path: str
    corpus_sha256: str
    case_count: int
    limit: int
    retrieval_kernel_authority: str | None
    runtime_provenance: object


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphProductionClosureReport:
    """Serializable final-ranking and graph-expansion production evidence."""

    environment: GraphProductionEnvironment
    cases: tuple[GraphProductionCaseReport, ...]
    summary: GraphProductionSummary
    failures: tuple[str, ...]


def _parse_args() -> _GraphClosureConfig:
    """Parse and validate Phase 9 graph closure CLI options."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare fixed HYBRID baseline with the AUTO production graph path and "
            "record final top-k quality plus graph expansion diagnostics."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--output", type=Path, dest="output_path")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 50:
        parser.error("--limit must be between 1 and 50")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    try:
        all_cases = load_memory_eval_cases(args.corpus)
    except (OSError, ValueError) as exc:
        parser.error(f"invalid --corpus file: {exc}")
    cases = tuple(
        case
        for case in all_cases
        if case.query_class is MemoryEvalQueryClass.MULTI_HOP_GRAPH
    )
    if not cases:
        parser.error("--corpus contains no MULTI_HOP_GRAPH cases")
    return _GraphClosureConfig(
        base_url=args.base_url.rstrip("/"),
        corpus_path=args.corpus,
        cases=cases,
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
        token_env=args.token_env,
        output_path=args.output_path,
    )


def _request_headers(token_env: str) -> dict[str, str]:
    """Build optional bearer headers for local benchmark access."""
    token = os.getenv(token_env)
    if token is None or not token.strip():
        return {}
    return {"Authorization": f"Bearer {token.strip()}"}


def _diagnostics_payload(case: MemoryEvalCase, limit: int) -> dict[str, object]:
    """Build the explain request that mirrors the production AUTO search."""
    payload: dict[str, object] = {
        "query": case.query,
        "strategy": _PRODUCTION_STRATEGY,
        "limit": limit,
    }
    if case.project is not None:
        payload["project"] = case.project
    if case.include_scopes:
        payload["include_scopes"] = list(case.include_scopes)
    if case.include_lifecycle_statuses:
        payload["include_lifecycle_statuses"] = list(case.include_lifecycle_statuses)
    return payload


def _mapping(value: object, label: str) -> dict[str, object]:
    """Narrow one decoded JSON object for strict benchmark parsing."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[object]:
    """Return one decoded list without coercing other JSON shapes."""
    return value if isinstance(value, list) else []


def _required_int(mapping: dict[str, object], key: str) -> int:
    """Return one strict integer diagnostics field."""
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"diagnostics field {key} must be an integer")
    return value


def _required_float(mapping: dict[str, object], key: str) -> float:
    """Return one numeric diagnostics field as float."""
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"diagnostics field {key} must be numeric")
    return float(value)


def _required_bool(mapping: dict[str, object], key: str) -> bool:
    """Return one strict boolean diagnostics field."""
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"diagnostics field {key} must be boolean")
    return value


def _required_string(mapping: dict[str, object], key: str) -> str:
    """Return one strict string diagnostics field."""
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ValueError(f"diagnostics field {key} must be a string")
    return value


def _optional_graph_depth(trace: dict[str, object]) -> int | None:
    """Read the planner-authoritative graph depth from the explain trace."""
    raw_plan = trace.get("retrieval_plan")
    if raw_plan is None:
        return None
    plan = _mapping(raw_plan, "retrieval_plan")
    return _required_int(plan, "graph_depth")


async def observe_graph_diagnostics(
    client: httpx.AsyncClient,
    case: MemoryEvalCase,
    limit: int,
) -> GraphExpansionDiagnostics:
    """Execute the normal explained AUTO path and collect bounded graph counters."""
    started_ns = perf_counter_ns()
    response = await client.post(
        DIAGNOSTICS_PATH,
        json=_diagnostics_payload(case, limit),
    )
    request_elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
    if response.is_error:
        detail = " ".join(response.text.split())[:240]
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    payload = _mapping(response.json(), "diagnostics response")
    trace = _mapping(payload.get("trace"), "diagnostics trace")
    timings = _mapping(trace.get("timings"), "diagnostics timings")
    raw_matches = [
        raw_match
        for raw_match in _sequence(payload.get("matches"))
        if isinstance(raw_match, dict)
    ]
    final_titles = tuple(
        title
        for raw_match in raw_matches
        for title in (raw_match.get("title"),)
        if isinstance(title, str)
    )
    max_graph_evidence_count = max(
        (_required_int(raw_match, "graph_evidence_count") for raw_match in raw_matches),
        default=0,
    )
    return GraphExpansionDiagnostics(
        effective_strategy=_required_string(trace, "effective_strategy"),
        planned_graph_depth=_optional_graph_depth(trace),
        discovered_candidate_count=_required_int(
            trace, "graph_expansion_discovered_candidate_count"
        ),
        selected_candidate_count=_required_int(
            trace, "graph_expansion_selected_candidate_count"
        ),
        hydrated_candidate_count=_required_int(
            trace, "graph_expansion_hydrated_candidate_count"
        ),
        filtered_candidate_count=_required_int(
            trace, "graph_expansion_filtered_candidate_count"
        ),
        appended_candidate_count=_required_int(
            trace, "graph_expansion_appended_candidate_count"
        ),
        expansion_applied=_required_bool(trace, "graph_expansion_applied"),
        expansion_degraded=_required_bool(trace, "graph_expansion_degraded"),
        graph_expansion_ms=_required_float(timings, "graph_expansion_ms"),
        total_ms=_required_float(timings, "total_ms"),
        request_elapsed_ms=request_elapsed_ms,
        final_titles=final_titles,
        max_graph_evidence_count=max_graph_evidence_count,
    )


def _expected_hit_indices(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
    limit: int,
) -> set[int]:
    """Return reviewed expected-memory indices reached in a bounded top-k prefix."""
    hits: set[int] = set()
    ranked_count = min(
        limit,
        max(len(observation.retrieved_context_ids), len(observation.retrieved_titles)),
    )
    expected_count = max(len(case.expected_context_ids), len(case.expected_titles))
    for rank_index in range(ranked_count):
        context_id = (
            observation.retrieved_context_ids[rank_index]
            if rank_index < len(observation.retrieved_context_ids)
            else None
        )
        title = (
            observation.retrieved_titles[rank_index]
            if rank_index < len(observation.retrieved_titles)
            else None
        )
        for expected_index in range(expected_count):
            expected_id = (
                case.expected_context_ids[expected_index]
                if expected_index < len(case.expected_context_ids)
                else None
            )
            expected_title = (
                case.expected_titles[expected_index]
                if expected_index < len(case.expected_titles)
                else None
            )
            if (expected_id is not None and context_id == expected_id) or (
                expected_title is not None and title == expected_title
            ):
                hits.add(expected_index)
                break
    return hits


def _quality(
    case: MemoryEvalCase,
    strategy: str,
    observation: MemoryEvalObservation,
) -> GraphFinalQuality:
    """Build true expected-recall and rank-sensitive final top-k quality."""
    metrics = summarize_memory_eval_case(case, strategy, [observation], [])
    expected_total = max(len(case.expected_context_ids), len(case.expected_titles))
    if expected_total < 1:
        raise ValueError("graph production truth requires expected memories")

    def hits_at(limit: int) -> int:
        return len(_expected_hit_indices(case, observation, limit))

    hit_1 = hits_at(1)
    hit_3 = hits_at(3)
    hit_5 = hits_at(5)
    return GraphFinalQuality(
        effective_strategy=observation.effective_strategy,
        hit_at_1=float(hit_1 > 0),
        hit_at_3=float(hit_3 > 0),
        hit_at_5=float(hit_5 > 0),
        expected_recall_at_1=hit_1 / expected_total,
        expected_recall_at_3=hit_3 / expected_total,
        expected_recall_at_5=hit_5 / expected_total,
        mean_reciprocal_rank=metrics.mean_reciprocal_rank or 0.0,
        ndcg_at_5=metrics.ndcg_at_5 or 0.0,
        multi_hop_success=metrics.multi_hop_success_rate or 0.0,
        latency_ms=observation.elapsed_ms,
    )


async def _read_runtime_evidence(
    client: httpx.AsyncClient,
) -> tuple[str | None, object]:
    """Read native retrieval authority and runtime provenance without mutation."""
    rag_response = await client.get(RAG_STATUS_PATH)
    authority = (
        None
        if rag_response.is_error
        else rag_response.headers.get(RETRIEVAL_KERNEL_AUTHORITY_HEADER)
    )
    readiness_response = await client.get(READINESS_PATH)
    if readiness_response.is_error:
        detail = " ".join(readiness_response.text.split())[:240]
        return authority, {
            "status_code": readiness_response.status_code,
            "error": detail,
        }
    readiness = _mapping(readiness_response.json(), "readiness response")
    return authority, readiness.get("runtime")


async def _run_case(
    client: httpx.AsyncClient,
    case: MemoryEvalCase,
    limit: int,
) -> GraphProductionCaseReport:
    """Run baseline, production AUTO, and explained AUTO for one truth case."""
    baseline_observation = await observe_memory_search(
        client, case, _BASELINE_STRATEGY, limit
    )
    production_observation = await observe_memory_search(
        client, case, _PRODUCTION_STRATEGY, limit
    )
    diagnostics = await observe_graph_diagnostics(client, case, limit)
    return GraphProductionCaseReport(
        case_id=case.case_id,
        query=case.query,
        baseline=_quality(case, _BASELINE_STRATEGY, baseline_observation),
        production=_quality(case, _PRODUCTION_STRATEGY, production_observation),
        diagnostics=diagnostics,
        final_ranking_matches_diagnostics=(
            production_observation.retrieved_titles == diagnostics.final_titles
        ),
    )


def _mean(values: tuple[float, ...]) -> float:
    """Return one rounded equal-case arithmetic mean."""
    return 0.0 if not values else round(statistics.fmean(values), 6)


def _ratio(numerator: int, denominator: int) -> float:
    """Return one rounded bounded operational yield ratio."""
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def summarize_graph_production(
    cases: tuple[GraphProductionCaseReport, ...],
    failures: tuple[str, ...],
) -> GraphProductionSummary:
    """Summarize quality deltas, selector yields, latency, and closure invariants."""
    baseline_hit_at_5 = _mean(tuple(item.baseline.hit_at_5 for item in cases))
    production_hit_at_5 = _mean(tuple(item.production.hit_at_5 for item in cases))
    baseline_recall = _mean(tuple(item.baseline.expected_recall_at_5 for item in cases))
    production_recall = _mean(
        tuple(item.production.expected_recall_at_5 for item in cases)
    )
    baseline_mrr = _mean(tuple(item.baseline.mean_reciprocal_rank for item in cases))
    production_mrr = _mean(
        tuple(item.production.mean_reciprocal_rank for item in cases)
    )
    baseline_multi_hop = _mean(tuple(item.baseline.multi_hop_success for item in cases))
    production_multi_hop = _mean(
        tuple(item.production.multi_hop_success for item in cases)
    )
    total_discovered = sum(
        item.diagnostics.discovered_candidate_count for item in cases
    )
    total_selected = sum(item.diagnostics.selected_candidate_count for item in cases)
    total_hydrated = sum(item.diagnostics.hydrated_candidate_count for item in cases)
    total_appended = sum(item.diagnostics.appended_candidate_count for item in cases)
    ranking_parity_rate = _mean(
        tuple(float(item.final_ranking_matches_diagnostics) for item in cases)
    )
    provenance_cases = tuple(
        item
        for item in cases
        if item.diagnostics.appended_candidate_count > 0
        and item.diagnostics.planned_graph_depth is not None
        and item.diagnostics.planned_graph_depth > 0
    )
    complete_path_provenance_rate = _ratio(
        sum(
            item.diagnostics.max_graph_evidence_count
            >= (item.diagnostics.planned_graph_depth or 0)
            for item in provenance_cases
        ),
        len(provenance_cases),
    )
    depth_mismatch_count = sum(
        item.diagnostics.planned_graph_depth != _EXPECTED_GRAPH_DEPTH for item in cases
    )
    degraded_case_count = sum(item.diagnostics.expansion_degraded for item in cases)
    effective_strategy_mismatch_count = sum(
        item.production.effective_strategy != _BASELINE_STRATEGY
        or item.diagnostics.effective_strategy != _BASELINE_STRATEGY
        for item in cases
    )
    quality_non_regression = (
        production_hit_at_5 >= baseline_hit_at_5
        and production_recall >= baseline_recall
        and production_mrr >= baseline_mrr
    )
    closure_ready = (
        bool(cases)
        and not failures
        and ranking_parity_rate == 1.0
        and bool(provenance_cases)
        and complete_path_provenance_rate == 1.0
        and depth_mismatch_count == 0
        and degraded_case_count == 0
        and effective_strategy_mismatch_count == 0
        and quality_non_regression
    )
    return GraphProductionSummary(
        case_count=len(cases),
        baseline_hit_at_5=baseline_hit_at_5,
        production_hit_at_5=production_hit_at_5,
        baseline_expected_recall_at_5=baseline_recall,
        production_expected_recall_at_5=production_recall,
        expected_recall_at_5_delta=round(production_recall - baseline_recall, 6),
        baseline_mean_reciprocal_rank=baseline_mrr,
        production_mean_reciprocal_rank=production_mrr,
        mean_reciprocal_rank_delta=round(production_mrr - baseline_mrr, 6),
        baseline_multi_hop_success_rate=baseline_multi_hop,
        production_multi_hop_success_rate=production_multi_hop,
        multi_hop_success_rate_delta=round(
            production_multi_hop - baseline_multi_hop, 6
        ),
        baseline_search_latency=summarize_latencies(
            tuple(item.baseline.latency_ms for item in cases)
        ),
        production_search_latency=summarize_latencies(
            tuple(item.production.latency_ms for item in cases)
        ),
        graph_expansion_latency=summarize_latencies(
            tuple(item.diagnostics.graph_expansion_ms for item in cases)
        ),
        explained_total_latency=summarize_latencies(
            tuple(item.diagnostics.total_ms for item in cases)
        ),
        average_discovered_candidate_count=_mean(
            tuple(float(item.diagnostics.discovered_candidate_count) for item in cases)
        ),
        average_selected_candidate_count=_mean(
            tuple(float(item.diagnostics.selected_candidate_count) for item in cases)
        ),
        average_hydrated_candidate_count=_mean(
            tuple(float(item.diagnostics.hydrated_candidate_count) for item in cases)
        ),
        average_filtered_candidate_count=_mean(
            tuple(float(item.diagnostics.filtered_candidate_count) for item in cases)
        ),
        average_appended_candidate_count=_mean(
            tuple(float(item.diagnostics.appended_candidate_count) for item in cases)
        ),
        selector_retention_rate=_ratio(total_selected, total_discovered),
        hydration_yield=_ratio(total_hydrated, total_selected),
        final_append_yield=_ratio(total_appended, total_hydrated),
        ranking_parity_rate=ranking_parity_rate,
        provenance_observed_case_count=len(provenance_cases),
        complete_path_provenance_rate=complete_path_provenance_rate,
        graph_depth_mismatch_count=depth_mismatch_count,
        degraded_case_count=degraded_case_count,
        effective_strategy_mismatch_count=effective_strategy_mismatch_count,
        quality_non_regression=quality_non_regression,
        closure_ready=closure_ready,
    )


async def _run(config: _GraphClosureConfig) -> GraphProductionClosureReport:
    """Execute all reviewed multi-hop cases through baseline and production paths."""
    timeout = httpx.Timeout(config.timeout_seconds)
    case_reports: list[GraphProductionCaseReport] = []
    failures: list[str] = []
    async with httpx.AsyncClient(
        base_url=config.base_url,
        timeout=timeout,
        headers=_request_headers(config.token_env),
    ) as client:
        authority, runtime_provenance = await _read_runtime_evidence(client)
        for case in config.cases:
            try:
                case_reports.append(await _run_case(client, case, config.limit))
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                failures.append(f"{case.case_id}: {type(exc).__name__}: {exc}")
    cases = tuple(case_reports)
    corpus_bytes = config.corpus_path.read_bytes()
    return GraphProductionClosureReport(
        environment=GraphProductionEnvironment(
            measured_at=datetime.now(UTC).isoformat(),
            base_url=config.base_url,
            corpus_path=str(config.corpus_path.resolve()),
            corpus_sha256=hashlib.sha256(corpus_bytes).hexdigest(),
            case_count=len(config.cases),
            limit=config.limit,
            retrieval_kernel_authority=authority,
            runtime_provenance=runtime_provenance,
        ),
        cases=cases,
        summary=summarize_graph_production(cases, tuple(failures)),
        failures=tuple(failures),
    )


def main() -> None:
    """Run the Phase 9 production graph closure suite and emit JSON evidence."""
    config = _parse_args()
    report = asyncio.run(_run(config))
    rendered = orjson.dumps(
        asdict(report),
        option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
    )
    sys.stdout.buffer.write(rendered + b"\n")
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_bytes(rendered + b"\n")


if __name__ == "__main__":
    main()
