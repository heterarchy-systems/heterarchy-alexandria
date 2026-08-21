"""Pure temporal policies for memory reconciliation."""

from __future__ import annotations

from datetime import datetime


def intervals_overlap(
    left_from: datetime | None,
    left_to: datetime | None,
    right_from: datetime | None,
    right_to: datetime | None,
) -> bool:
    """Return whether two open-ended validity intervals overlap.

    Args:
        left_from: Left from.
        left_to: Left to.
        right_from: Right from.
        right_to: Right to.

    Returns:
        bool: Operation result.
    """
    if left_to is not None and right_from is not None and left_to < right_from:
        return False
    return not (right_to is not None and left_from is not None and right_to < left_from)


def is_temporally_newer(
    candidate_valid_from: datetime | None,
    candidate_observed_at: datetime | None,
    existing_valid_from: datetime | None,
    existing_observed_at: datetime | None,
) -> bool:
    """Return whether candidate evidence is explicitly newer than existing evidence.

    Args:
        candidate_valid_from: Candidate valid from.
        candidate_observed_at: Candidate observed at.
        existing_valid_from: Existing valid from.
        existing_observed_at: Existing observed at.

    Returns:
        bool: Operation result.
    """
    candidate_time = candidate_valid_from or candidate_observed_at
    existing_time = existing_valid_from or existing_observed_at
    return (
        candidate_time is not None
        and existing_time is not None
        and candidate_time > existing_time
    )
