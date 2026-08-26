"""Stable current-state preference over explicit canonical temporal metadata."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.context_read_models import (
    ContextRecord,
    ContextSearchMatch,
)
from app.shared.types.extra_types import JSONValue

_TEMPORAL_METADATA_FIELDS = ("valid_from", "observed_at", "recorded_at")


def prefer_current_temporal_matches(
    matches: list[ContextSearchMatch],
    enabled: bool,
) -> list[ContextSearchMatch]:
    """Prefer explicitly newer current-state evidence without changing scores or membership.

    Args:
        matches: Ranked primary retrieval results.
        enabled: Whether the adaptive plan requested current-state preference.

    Returns:
        Stable reordered matches. Items without explicit temporal metadata remain in
        their original relative order after timestamped matches.
    """
    if not enabled or len(matches) < 2:
        return matches
    timestamped: list[tuple[datetime, int, ContextSearchMatch]] = []
    undated: list[ContextSearchMatch] = []
    for index, match in enumerate(matches):
        timestamp = _canonical_temporal_timestamp(match.context)
        if timestamp is None:
            undated.append(match)
            continue
        timestamped.append((timestamp, index, match))
    if len(timestamped) < 2 and not undated:
        return matches
    timestamped.sort(key=lambda item: item[0], reverse=True)
    return [item[2] for item in timestamped] + undated


def _canonical_temporal_timestamp(context: ContextRecord) -> datetime | None:
    """Return the strongest explicit canonical timestamp available for one Context.

    Args:
        context: Retrieved Context read model.

    Returns:
        First valid timezone-aware timestamp in semantic precedence order, or None.
    """
    for field_name in _TEMPORAL_METADATA_FIELDS:
        value = context.context_metadata.get(field_name)
        timestamp = _aware_datetime(value)
        if timestamp is not None:
            return timestamp
    return None


def _aware_datetime(value: JSONValue | None) -> datetime | None:
    """Parse one strict ISO timestamp without inventing timezone semantics.

    Args:
        value: Raw metadata value.

    Returns:
        Timezone-aware datetime when the value is a valid ISO timestamp, otherwise None.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None
