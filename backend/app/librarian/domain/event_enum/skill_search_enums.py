"""Feature-owned skill search enums."""

from __future__ import annotations

from enum import StrEnum


class SkillSearchDecision(StrEnum):
    """Search-first decision before creating an acquisition job."""

    FOUND_SUFFICIENT = "FOUND_SUFFICIENT"
    FOUND_PARTIAL = "FOUND_PARTIAL"
    NOT_FOUND = "NOT_FOUND"
    SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"
