"""Feature-owned source ref enums."""

from __future__ import annotations

from enum import StrEnum


class SourceRefType(StrEnum):
    """Lazy-loadable source categories exposed to librarian delegates."""

    CONTEXT = "CONTEXT"
    MEMORY_COMPACT = "MEMORY_COMPACT"
    LIBRARY_ITEM = "LIBRARY_ITEM"
    SKILL = "SKILL"
    PROMPT = "PROMPT"
