"""Tests for deterministic benchmark statistics."""

from __future__ import annotations

import pytest
from benchmarks.benchmark_statistics import (
    nearest_rank_percentile,
    summarize_latencies,
)


def test_nearest_rank_percentile_uses_observed_sample_values() -> None:
    """Percentiles should select an observed value without interpolation."""
    values = (1.0, 5.0, 2.0, 4.0, 3.0)

    assert nearest_rank_percentile(values, 0.50) == 3.0
    assert nearest_rank_percentile(values, 0.95) == 5.0


def test_nearest_rank_percentile_rejects_invalid_inputs() -> None:
    """Invalid samples and percentile ratios should fail explicitly."""
    with pytest.raises(ValueError, match="must not be empty"):
        nearest_rank_percentile((), 0.50)
    with pytest.raises(ValueError, match="between zero and one"):
        nearest_rank_percentile((1.0,), 1.01)


def test_summarize_latencies_records_empty_and_populated_samples() -> None:
    """Reports should distinguish no samples from a zero-millisecond sample."""
    empty = summarize_latencies(())
    populated = summarize_latencies((0.0, 1.2344, 2.3456))

    assert empty.sample_count == 0
    assert empty.p50_ms is None
    assert populated.sample_count == 3
    assert populated.p50_ms == 1.234
    assert populated.p95_ms == 2.346
    assert populated.mean_ms == 1.193
    assert populated.min_ms == 0.0
    assert populated.max_ms == 2.346
