"""Backend-independent vector relevance scoring."""

from __future__ import annotations


def cosine_distance_to_score(distance: float) -> float:
    """Convert cosine distance into a bounded similarity score.

    Args:
        distance: Cosine distance value to normalize.

    Returns:
        Similarity score bounded to the inclusive range from zero to one.
    """
    bounded_distance = min(max(distance, 0.0), 2.0)
    return 1.0 - (bounded_distance / 2.0)
