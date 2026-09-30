"""Shared immutable embedding vector value contracts."""

from __future__ import annotations

import math
from collections.abc import Iterable

EMBEDDING_VECTOR_DIMENSIONS = 384

type EmbeddingVector = tuple[float, ...]


def normalize_embedding_vector(
    vector: Iterable[float | int],
    expected_dimensions: int | None = None,
) -> EmbeddingVector:
    """Normalize a finite embedding vector into an immutable tuple.

    Args:
        vector: Ordered integer or floating-point values, normalized to floats.
        expected_dimensions: Required vector length when known.

    Returns:
        Finite immutable embedding values.

    Raises:
        ValueError: If the vector is empty, non-finite, or has the wrong size.
    """
    values = tuple(float(value) for value in vector)
    if not values:
        raise ValueError("Embedding vector is empty")
    if expected_dimensions is not None and len(values) != expected_dimensions:
        raise ValueError(
            "Embedding vector has unexpected dimensions: "
            f"expected {expected_dimensions}, received {len(values)}"
        )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Embedding vector contains a non-finite value")
    return values
