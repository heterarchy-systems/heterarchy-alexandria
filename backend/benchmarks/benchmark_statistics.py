"""Shared deterministic statistics for Alexandria benchmark reports."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Nearest-rank latency summary for one benchmark operation."""

    sample_count: int
    p50_ms: float | None
    p95_ms: float | None
    mean_ms: float | None
    min_ms: float | None
    max_ms: float | None


def nearest_rank_percentile(values: tuple[float, ...], ratio: float) -> float:
    """Return one nearest-rank percentile from a non-empty sample.

    Args:
        values: Measured values.
        ratio: Percentile ratio in the inclusive range from zero to one.

    Returns:
        Selected nearest-rank value.

    Raises:
        ValueError: If the sample is empty or the ratio is outside zero to one.
    """
    if not values:
        raise ValueError("percentile sample must not be empty")
    if ratio < 0 or ratio > 1:
        raise ValueError("percentile ratio must be between zero and one")
    ordered = sorted(values)
    rank = max(1, ceil(len(ordered) * ratio))
    return ordered[rank - 1]


def summarize_latencies(values: tuple[float, ...]) -> LatencySummary:
    """Return rounded latency statistics without imposing machine-specific limits.

    Args:
        values: Measured milliseconds.

    Returns:
        Empty or populated latency summary.
    """
    if not values:
        return LatencySummary(
            sample_count=0,
            p50_ms=None,
            p95_ms=None,
            mean_ms=None,
            min_ms=None,
            max_ms=None,
        )
    return LatencySummary(
        sample_count=len(values),
        p50_ms=round(nearest_rank_percentile(values, 0.50), 3),
        p95_ms=round(nearest_rank_percentile(values, 0.95), 3),
        mean_ms=round(statistics.fmean(values), 3),
        min_ms=round(min(values), 3),
        max_ms=round(max(values), 3),
    )
