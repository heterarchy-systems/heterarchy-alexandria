"""Pure Golden Query parsing and quality aggregation for Context RAG benchmarks."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from benchmarks.benchmark_statistics import summarize_latencies
from benchmarks.context_rag_benchmark_contracts import (
    BenchmarkQuery,
    CaseSummary,
    SearchObservation,
    StrategyQualitySummary,
)

GOLDEN_CASE_SCHEMA_VERSION = 1


def load_golden_queries(path: Path) -> tuple[BenchmarkQuery, ...]:
    """Load and validate a private/local Golden Query specification.

    Args:
        path: JSON specification path.

    Returns:
        Validated benchmark queries.

    Raises:
        ValueError: If the specification shape or values are invalid.
    """
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    payload = _mapping(raw)
    if payload.get("schema_version") != GOLDEN_CASE_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {GOLDEN_CASE_SCHEMA_VERSION}")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases must be a non-empty JSON array")

    queries: list[BenchmarkQuery] = []
    seen_queries: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _mapping(raw_case)
        query = case.get("query")
        project = case.get("project")
        expected_ids = case.get("expected_context_ids", [])
        expected_titles = case.get("expected_titles", [])
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"cases[{index}].query must be non-empty text")
        if project is not None and (
            not isinstance(project, str) or not project.strip()
        ):
            raise ValueError(f"cases[{index}].project must be non-empty text when set")
        normalized_expected_ids = _normalize_expected_values(
            expected_ids,
            field_path=f"cases[{index}].expected_context_ids",
        )
        normalized_expected_titles = _normalize_expected_values(
            expected_titles,
            field_path=f"cases[{index}].expected_titles",
        )
        if not normalized_expected_ids and not normalized_expected_titles:
            raise ValueError(
                f"cases[{index}] must define expected_context_ids or expected_titles"
            )
        normalized_query = query.strip()
        if normalized_query in seen_queries:
            raise ValueError(f"duplicate golden query: {normalized_query}")
        seen_queries.add(normalized_query)
        queries.append(
            BenchmarkQuery(
                query=normalized_query,
                project=project.strip() if isinstance(project, str) else None,
                expected_context_ids=normalized_expected_ids,
                expected_titles=normalized_expected_titles,
            )
        )
    return tuple(queries)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Golden Query payload must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _normalize_expected_values(
    value: object,
    field_path: str,
) -> tuple[str, ...]:
    """Validate one optional array of stable Golden Query identities.

    Args:
        value: Raw JSON value.
        field_path: Human-readable validation path.

    Returns:
        Deduplicated non-empty text values.

    Raises:
        ValueError: If the value is not an array of non-empty strings.
    """
    if not isinstance(value, list):
        raise ValueError(f"{field_path} must be a JSON array")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_path}[{index}] must be non-empty text")
        normalized.append(item.strip())
    return tuple(dict.fromkeys(normalized))


def retrieved_context_ids(matches: list[object]) -> tuple[str, ...]:
    """Return public canonical Context identities in response order.

    Args:
        matches: Raw API match objects.

    Returns:
        Non-empty Context ids in ranking order.
    """
    context_ids: list[str] = []
    for raw_match in matches:
        if not isinstance(raw_match, dict):
            continue
        canonical_context_id = raw_match.get("canonical_context_id")
        if isinstance(canonical_context_id, str) and canonical_context_id:
            context_ids.append(canonical_context_id)
            continue
        context = raw_match.get("context")
        if not isinstance(context, dict):
            continue
        context_id = context.get("id")
        if isinstance(context_id, str) and context_id:
            context_ids.append(context_id)
    return tuple(context_ids)


def retrieved_titles(matches: list[object]) -> tuple[str, ...]:
    """Return result titles in ranking order for Obsidian Golden Queries.

    Args:
        matches: Raw API match objects.

    Returns:
        Non-empty context titles in response order.
    """
    titles: list[str] = []
    for raw_match in matches:
        if not isinstance(raw_match, dict):
            continue
        context = raw_match.get("context")
        if not isinstance(context, dict):
            continue
        title = context.get("title")
        if isinstance(title, str) and title:
            titles.append(title)
    return tuple(titles)


def _first_expected_rank(
    benchmark_query: BenchmarkQuery,
    observation: SearchObservation,
) -> int | None:
    """Return the first rank matching an expected Context id or Obsidian title."""
    expected_ids = set(benchmark_query.expected_context_ids)
    expected_titles = set(benchmark_query.expected_titles)
    result_count = max(
        len(observation.retrieved_context_ids),
        len(observation.retrieved_titles),
    )
    for index in range(result_count):
        context_id = (
            observation.retrieved_context_ids[index]
            if index < len(observation.retrieved_context_ids)
            else None
        )
        title = (
            observation.retrieved_titles[index]
            if index < len(observation.retrieved_titles)
            else None
        )
        if context_id in expected_ids or title in expected_titles:
            return index + 1
    return None


def _quality_metrics(
    benchmark_query: BenchmarkQuery,
    observations: list[SearchObservation],
) -> tuple[float | None, float | None, float | None]:
    if (
        not benchmark_query.expected_context_ids and not benchmark_query.expected_titles
    ) or not observations:
        return None, None, None
    ranks = tuple(_first_expected_rank(benchmark_query, item) for item in observations)
    recall_at_1 = statistics.fmean(float(rank == 1) for rank in ranks)
    recall_at_3 = statistics.fmean(
        float(rank is not None and rank <= 3) for rank in ranks
    )
    mean_reciprocal_rank = statistics.fmean(
        0.0 if rank is None else 1.0 / rank for rank in ranks
    )
    return (
        round(recall_at_1, 6),
        round(recall_at_3, 6),
        round(mean_reciprocal_rank, 6),
    )


def summarize_case(
    benchmark_query: BenchmarkQuery,
    strategy: str,
    observations: list[SearchObservation],
    failures: list[str],
) -> CaseSummary:
    """Aggregate one query/strategy case without machine-specific thresholds."""
    latency = summarize_latencies(tuple(item.elapsed_ms for item in observations))
    if not observations:
        return CaseSummary(
            query=benchmark_query.query,
            project=benchmark_query.project,
            requested_strategy=strategy,
            expected_context_ids=benchmark_query.expected_context_ids,
            expected_titles=benchmark_query.expected_titles,
            successful_samples=0,
            failed_samples=len(failures),
            latency_p50_ms=None,
            latency_p95_ms=None,
            latency_mean_ms=None,
            latency_min_ms=None,
            latency_max_ms=None,
            response_bytes_p50=None,
            match_count_min=None,
            match_count_max=None,
            warning_count_max=None,
            graph_evidence_match_count_max=None,
            effective_strategies=(),
            retrieved_context_id_variants=(),
            retrieved_title_variants=(),
            ranking_stable=None,
            recall_at_1=None,
            recall_at_3=None,
            mean_reciprocal_rank=None,
            failures=tuple(failures),
        )

    response_sizes = sorted(item.response_bytes for item in observations)
    response_bytes_p50 = response_sizes[(len(response_sizes) - 1) // 2]
    effective_strategies = tuple(
        sorted(
            {
                item.effective_strategy
                for item in observations
                if item.effective_strategy is not None
            }
        )
    )
    ranking_variants = tuple(
        sorted({item.retrieved_context_ids for item in observations})
    )
    title_variants = tuple(sorted({item.retrieved_titles for item in observations}))
    recall_at_1, recall_at_3, mean_reciprocal_rank = _quality_metrics(
        benchmark_query,
        observations,
    )
    return CaseSummary(
        query=benchmark_query.query,
        project=benchmark_query.project,
        requested_strategy=strategy,
        expected_context_ids=benchmark_query.expected_context_ids,
        expected_titles=benchmark_query.expected_titles,
        successful_samples=len(observations),
        failed_samples=len(failures),
        latency_p50_ms=latency.p50_ms,
        latency_p95_ms=latency.p95_ms,
        latency_mean_ms=latency.mean_ms,
        latency_min_ms=latency.min_ms,
        latency_max_ms=latency.max_ms,
        response_bytes_p50=response_bytes_p50,
        match_count_min=min(item.match_count for item in observations),
        match_count_max=max(item.match_count for item in observations),
        warning_count_max=max(item.warning_count for item in observations),
        graph_evidence_match_count_max=max(
            item.graph_evidence_match_count for item in observations
        ),
        effective_strategies=effective_strategies,
        retrieved_context_id_variants=ranking_variants,
        retrieved_title_variants=title_variants,
        ranking_stable=len(ranking_variants) == 1 and len(title_variants) == 1,
        recall_at_1=recall_at_1,
        recall_at_3=recall_at_3,
        mean_reciprocal_rank=mean_reciprocal_rank,
        failures=tuple(failures),
    )


def summarize_strategy_quality(
    strategy: str,
    cases: tuple[CaseSummary, ...],
) -> StrategyQualitySummary:
    """Equal-weight evaluable Golden Queries for one requested strategy."""
    evaluated = tuple(
        case
        for case in cases
        if case.requested_strategy == strategy and case.recall_at_1 is not None
    )
    if not evaluated:
        return StrategyQualitySummary(
            requested_strategy=strategy,
            evaluated_cases=0,
            recall_at_1=None,
            recall_at_3=None,
            mean_reciprocal_rank=None,
            unstable_case_count=0,
        )
    return StrategyQualitySummary(
        requested_strategy=strategy,
        evaluated_cases=len(evaluated),
        recall_at_1=round(
            statistics.fmean(
                case.recall_at_1 for case in evaluated if case.recall_at_1 is not None
            ),
            6,
        ),
        recall_at_3=round(
            statistics.fmean(
                case.recall_at_3 for case in evaluated if case.recall_at_3 is not None
            ),
            6,
        ),
        mean_reciprocal_rank=round(
            statistics.fmean(
                case.mean_reciprocal_rank
                for case in evaluated
                if case.mean_reciprocal_rank is not None
            ),
            6,
        ),
        unstable_case_count=sum(case.ranking_stable is False for case in evaluated),
    )
