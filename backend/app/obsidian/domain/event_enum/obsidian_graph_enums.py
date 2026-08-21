"""Feature-owned obsidian graph enums."""

from __future__ import annotations

from enum import StrEnum


class ObsidianGraphProjectionIssueCode(StrEnum):
    """Reasons an indexed row cannot be projected without qualification."""

    INDEX_ERROR = "index_error"
    MISSING_TARGET_NOTE = "missing_target_note"
    AMBIGUOUS_TARGET_NOTE = "ambiguous_target_note"


class ObsidianGraphDirection(StrEnum):
    """Direction of one projected relationship relative to a requested note."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"


class ObsidianGraphContextSignalType(StrEnum):
    """Provider-owned semantic classification for Context graph evidence."""

    GRAPH_PROXIMITY = "graph_proximity"
    LINEAGE = "lineage"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    SUPERSEDES_CANDIDATE = "supersedes_candidate"
    RESUME_PATH = "resume_path"
    IMPACT_ANALYSIS = "impact_analysis"
