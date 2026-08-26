"""Pure deterministic metrics for the Alexandria Memory Evaluation Suite."""

from __future__ import annotations

import math
import statistics

from benchmarks.benchmark_statistics import summarize_latencies
from benchmarks.memory_eval_contracts import (
    MemoryEvalCase,
    MemoryEvalCaseMetrics,
    MemoryEvalObservation,
    MemoryEvalQueryClass,
    MemoryEvalStrategyMetrics,
)


def _ranked_identity_count(observation: MemoryEvalObservation) -> int:
    """Return aligned ranked result count used by identity metrics.

    Args:
        observation: One retrieval observation.

    Returns:
        Maximum available ranked identity/title length.
    """
    return max(
        len(observation.retrieved_context_ids),
        len(observation.retrieved_titles),
    )


def _value_at(values: tuple[str, ...], index: int) -> str | None:
    """Read one optional ranked string without widening the caller contract.

    Args:
        values: Ranked string values.
        index: Zero-based rank index.

    Returns:
        Ranked value when present, otherwise None.
    """
    return values[index] if index < len(values) else None


def _expected_key_at_rank(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
    index: int,
) -> str | None:
    """Return the stable expected identity matched at one result rank.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.
        index: Zero-based result rank.

    Returns:
        Namespaced expected identity or title when this rank is relevant.
    """
    context_id = _value_at(observation.retrieved_context_ids, index)
    if context_id is not None and context_id in case.expected_context_ids:
        return f"id:{context_id}"
    title = _value_at(observation.retrieved_titles, index)
    if title is not None and title in case.expected_titles:
        return f"title:{title}"
    return None


def _is_forbidden_rank(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
    index: int,
) -> bool:
    """Return whether one ranked result violates explicit obsolete/incorrect truth.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.
        index: Zero-based result rank.

    Returns:
        True when the result id or title is explicitly forbidden.
    """
    context_id = _value_at(observation.retrieved_context_ids, index)
    title = _value_at(observation.retrieved_titles, index)
    return (context_id is not None and context_id in case.forbidden_context_ids) or (
        title is not None and title in case.forbidden_titles
    )


def _first_expected_rank(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
) -> int | None:
    """Return the first one-based rank containing accepted memory truth.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.

    Returns:
        First accepted rank or None when no expected memory was retrieved.
    """
    for index in range(_ranked_identity_count(observation)):
        if _expected_key_at_rank(case, observation, index) is not None:
            return index + 1
    return None


def _distinct_expected_hits(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
    limit: int,
) -> int:
    """Count distinct expected memories preserved inside a bounded result prefix.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.
        limit: Maximum ranks examined.

    Returns:
        Distinct expected identity count inside the prefix.
    """
    hits = {
        key
        for index in range(min(limit, _ranked_identity_count(observation)))
        if (key := _expected_key_at_rank(case, observation, index)) is not None
    }
    return len(hits)


def _forbidden_hit_count(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
    limit: int,
) -> int:
    """Count explicitly forbidden memories inside a bounded result prefix.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.
        limit: Maximum ranks examined.

    Returns:
        Number of forbidden ranked rows inside the prefix.
    """
    return sum(
        _is_forbidden_rank(case, observation, index)
        for index in range(min(limit, _ranked_identity_count(observation)))
    )


def _ndcg_at_5(
    case: MemoryEvalCase, observation: MemoryEvalObservation
) -> float | None:
    """Compute binary nDCG@5 over explicit expected memories.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.

    Returns:
        Binary nDCG@5, or None for abstention-only cases.
    """
    expected_total = max(len(case.expected_context_ids), len(case.expected_titles))
    if case.expected_abstention or expected_total == 0:
        return None
    seen: set[str] = set()
    dcg = 0.0
    for index in range(min(5, _ranked_identity_count(observation))):
        key = _expected_key_at_rank(case, observation, index)
        if key is None or key in seen:
            continue
        seen.add(key)
        dcg += 1.0 / math.log2(index + 2)
    ideal_hits = min(5, expected_total)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return 0.0 if idcg == 0.0 else dcg / idcg


def _observation_metrics(
    case: MemoryEvalCase,
    observation: MemoryEvalObservation,
) -> dict[str, float | None]:
    """Compute memory-specific scalar metrics for one observation.

    Args:
        case: Explicit benchmark truth.
        observation: One retrieval observation.

    Returns:
        Metric-name to scalar mapping for aggregation.
    """
    first_rank = _first_expected_rank(case, observation)
    recall_at_1 = None if case.expected_abstention else float(first_rank == 1)
    recall_at_3 = (
        None
        if case.expected_abstention
        else float(first_rank is not None and first_rank <= 3)
    )
    recall_at_5 = (
        None
        if case.expected_abstention
        else float(first_rank is not None and first_rank <= 5)
    )
    reciprocal_rank = (
        None
        if case.expected_abstention
        else 0.0
        if first_rank is None
        else 1.0 / first_rank
    )
    forbidden_hits = _forbidden_hit_count(case, observation, 5)
    examined = min(5, _ranked_identity_count(observation))
    obsolete_memory_rate = (
        None
        if not case.forbidden_context_ids and not case.forbidden_titles
        else forbidden_hits / max(1, examined)
    )
    temporal_correctness = None
    if case.query_class is MemoryEvalQueryClass.TEMPORAL_CURRENT_STATE:
        temporal_correctness = float(first_rank == 1 and forbidden_hits == 0)
    superseded_leakage = None
    if case.query_class is MemoryEvalQueryClass.SUPERSESSION:
        superseded_leakage = float(forbidden_hits > 0)
    historical_current_precision = None
    if case.query_class in {
        MemoryEvalQueryClass.TEMPORAL_CURRENT_STATE,
        MemoryEvalQueryClass.SUPERSESSION,
    }:
        expected_hits = _distinct_expected_hits(case, observation, 5)
        adjudicated_hits = expected_hits + forbidden_hits
        historical_current_precision = (
            0.0 if adjudicated_hits == 0 else expected_hits / adjudicated_hits
        )
    experiential_recall_success = None
    if case.query_class is MemoryEvalQueryClass.EXPERIENTIAL_RECALL:
        experiential_recall_success = float(first_rank is not None and first_rank <= 3)
    procedural_recall_success = None
    if case.query_class is MemoryEvalQueryClass.PROCEDURAL_RECALL:
        procedural_recall_success = float(first_rank is not None and first_rank <= 3)
    wrong_premise_correction = None
    if case.query_class is MemoryEvalQueryClass.WRONG_PREMISE:
        wrong_premise_correction = float(
            first_rank is not None and first_rank <= 3 and forbidden_hits == 0
        )
    conflict_collapse = None
    if case.query_class is MemoryEvalQueryClass.CONFLICT_PRESERVATION:
        conflict_collapse = float(
            _distinct_expected_hits(case, observation, 5)
            < case.minimum_expected_matches
        )
    wrong_memory_rate = float(
        observation.match_count > 0
        if case.expected_abstention
        else first_rank is None or forbidden_hits > 0
    )
    abstention_accuracy = (
        float(observation.match_count == 0) if case.expected_abstention else None
    )
    multi_hop_success = None
    if case.query_class is MemoryEvalQueryClass.MULTI_HOP_GRAPH:
        required = set(case.required_graph_relations)
        multi_hop_success = float(
            _distinct_expected_hits(case, observation, 5)
            >= case.minimum_expected_matches
            and required.issubset(set(observation.graph_relations))
            and observation.graph_max_distance >= case.minimum_graph_distance
        )
    cross_language_success = None
    if case.query_class is MemoryEvalQueryClass.CROSS_LANGUAGE:
        cross_language_success = float(first_rank is not None and first_rank <= 3)
    return {
        "recall_at_1": recall_at_1,
        "recall_at_3": recall_at_3,
        "recall_at_5": recall_at_5,
        "mean_reciprocal_rank": reciprocal_rank,
        "ndcg_at_5": _ndcg_at_5(case, observation),
        "temporal_correctness": temporal_correctness,
        "obsolete_memory_rate": obsolete_memory_rate,
        "superseded_memory_leakage_rate": superseded_leakage,
        "historical_current_precision": historical_current_precision,
        "experiential_recall_success_rate": experiential_recall_success,
        "procedural_recall_success_rate": procedural_recall_success,
        "wrong_premise_correction_rate": wrong_premise_correction,
        "conflict_collapse_rate": conflict_collapse,
        "wrong_memory_rate": wrong_memory_rate,
        "abstention_accuracy": abstention_accuracy,
        "multi_hop_success_rate": multi_hop_success,
        "cross_language_success_rate": cross_language_success,
    }


def _mean(values: list[float | None]) -> float | None:
    """Return a rounded mean while ignoring non-applicable metrics.

    Args:
        values: Optional metric values.

    Returns:
        Rounded mean or None when no value applies.
    """
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(statistics.fmean(present), 6)


def summarize_memory_eval_case(
    case: MemoryEvalCase,
    strategy: str,
    observations: list[MemoryEvalObservation],
    failures: list[str],
) -> MemoryEvalCaseMetrics:
    """Aggregate one memory-evaluation case without absolute latency gates.

    Args:
        case: Explicit benchmark truth.
        strategy: Requested retrieval strategy.
        observations: Successful repeated observations.
        failures: Sanitized failed observation messages.

    Returns:
        Per-case memory quality and latency summary.
    """
    latency = summarize_latencies(tuple(item.elapsed_ms for item in observations))
    metric_rows = [_observation_metrics(case, item) for item in observations]
    rankings = {
        (item.retrieved_context_ids, item.retrieved_titles) for item in observations
    }

    def metric(name: str) -> float | None:
        """Aggregate one named observation metric.

        Args:
            name: Metric key emitted by the pure observation evaluator.

        Returns:
            Equal-observation-weighted metric mean.
        """
        return _mean([row[name] for row in metric_rows])

    return MemoryEvalCaseMetrics(
        case_id=case.case_id,
        query_class=case.query_class,
        requested_strategy=strategy,
        observation_count=len(observations),
        failure_count=len(failures),
        ranking_stable=None if not observations else len(rankings) == 1,
        recall_at_1=metric("recall_at_1"),
        recall_at_3=metric("recall_at_3"),
        recall_at_5=metric("recall_at_5"),
        mean_reciprocal_rank=metric("mean_reciprocal_rank"),
        ndcg_at_5=metric("ndcg_at_5"),
        temporal_correctness=metric("temporal_correctness"),
        obsolete_memory_rate=metric("obsolete_memory_rate"),
        superseded_memory_leakage_rate=metric("superseded_memory_leakage_rate"),
        historical_current_precision=metric("historical_current_precision"),
        experiential_recall_success_rate=metric("experiential_recall_success_rate"),
        procedural_recall_success_rate=metric("procedural_recall_success_rate"),
        wrong_premise_correction_rate=metric("wrong_premise_correction_rate"),
        conflict_collapse_rate=metric("conflict_collapse_rate"),
        wrong_memory_rate=metric("wrong_memory_rate"),
        abstention_accuracy=metric("abstention_accuracy"),
        multi_hop_success_rate=metric("multi_hop_success_rate"),
        cross_language_success_rate=metric("cross_language_success_rate"),
        latency_p50_ms=latency.p50_ms,
        latency_p95_ms=latency.p95_ms,
        effective_strategies=tuple(
            sorted(
                {
                    item.effective_strategy
                    for item in observations
                    if item.effective_strategy is not None
                }
            )
        ),
        failures=tuple(failures),
    )


def summarize_memory_eval_strategy(
    strategy: str,
    cases: tuple[MemoryEvalCaseMetrics, ...],
) -> MemoryEvalStrategyMetrics:
    """Aggregate equal-case-weighted memory quality for one retrieval strategy.

    Args:
        strategy: Requested strategy identity.
        cases: All per-case summaries in the report.

    Returns:
        Strategy-level memory quality summary.
    """
    selected = tuple(case for case in cases if case.requested_strategy == strategy)
    return MemoryEvalStrategyMetrics(
        requested_strategy=strategy,
        evaluated_cases=len(selected),
        recall_at_1=_mean([case.recall_at_1 for case in selected]),
        recall_at_3=_mean([case.recall_at_3 for case in selected]),
        recall_at_5=_mean([case.recall_at_5 for case in selected]),
        mean_reciprocal_rank=_mean([case.mean_reciprocal_rank for case in selected]),
        ndcg_at_5=_mean([case.ndcg_at_5 for case in selected]),
        temporal_correctness=_mean([case.temporal_correctness for case in selected]),
        obsolete_memory_rate=_mean([case.obsolete_memory_rate for case in selected]),
        superseded_memory_leakage_rate=_mean(
            [case.superseded_memory_leakage_rate for case in selected]
        ),
        historical_current_precision=_mean(
            [case.historical_current_precision for case in selected]
        ),
        experiential_recall_success_rate=_mean(
            [case.experiential_recall_success_rate for case in selected]
        ),
        procedural_recall_success_rate=_mean(
            [case.procedural_recall_success_rate for case in selected]
        ),
        wrong_premise_correction_rate=_mean(
            [case.wrong_premise_correction_rate for case in selected]
        ),
        conflict_collapse_rate=_mean(
            [case.conflict_collapse_rate for case in selected]
        ),
        wrong_memory_rate=_mean([case.wrong_memory_rate for case in selected]),
        abstention_accuracy=_mean([case.abstention_accuracy for case in selected]),
        multi_hop_success_rate=_mean(
            [case.multi_hop_success_rate for case in selected]
        ),
        cross_language_success_rate=_mean(
            [case.cross_language_success_rate for case in selected]
        ),
        unstable_case_count=sum(case.ranking_stable is False for case in selected),
    )
