"""High-level agent-facing recall protocol enums."""

from __future__ import annotations

from enum import StrEnum


class RecallScopeMode(StrEnum):
    """How recall chooses its scope lanes."""

    AUTO = "AUTO"
    STRICT = "STRICT"


class RecallOutcome(StrEnum):
    """Bounded outcomes for one high-level recall request."""

    MATCHED = "MATCHED"
    NO_CONFIDENT_MATCH = "NO_CONFIDENT_MATCH"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"
    DEGRADED_SEARCH = "DEGRADED_SEARCH"


class RecallRoute(StrEnum):
    """Observable stages in the bounded recall cascade."""

    EXACT_SELECTOR = "EXACT_SELECTOR"
    PRIMARY_FTS = "PRIMARY_FTS"
    PRIMARY_SEMANTIC = "PRIMARY_SEMANTIC"
    RELATED_PROJECT_FTS = "RELATED_PROJECT_FTS"
    RELATED_PROJECT_SEMANTIC = "RELATED_PROJECT_SEMANTIC"
    GLOBAL_FTS = "GLOBAL_FTS"
    GLOBAL_SEMANTIC = "GLOBAL_SEMANTIC"
    TEMPORAL_HISTORICAL = "TEMPORAL_HISTORICAL"


class RecallStageStatus(StrEnum):
    """Status of one attempted or skipped cascade stage."""

    ATTEMPTED = "ATTEMPTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class RecallProjectAffinity(StrEnum):
    """Project relationship represented by a recalled match."""

    PRIMARY = "PRIMARY"
    RELATED = "RELATED"
    GLOBAL = "GLOBAL"
