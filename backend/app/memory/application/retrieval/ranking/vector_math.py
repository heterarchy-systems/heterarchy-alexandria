"""Vector mathematics used by memory retrieval."""

from __future__ import annotations

from collections.abc import Iterable


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    """Return cosine similarity for two vectors.

    Args:
        left: First vector.
        right: Second vector.

    Returns:
        Cosine similarity in the inclusive range allowed by vector content.
    """
    left_values = list(left)
    right_values = list(right)
    if len(left_values) != len(right_values) or not left_values:
        return 0.0
    dot = sum(
        l_value * r_value
        for l_value, r_value in zip(left_values, right_values, strict=True)
    )
    left_norm = sum(value * value for value in left_values) ** 0.5
    right_norm = sum(value * value for value in right_values) ** 0.5
    denominator = left_norm * right_norm
    if denominator == 0:
        return 0.0
    similarity = dot / denominator
    return similarity
