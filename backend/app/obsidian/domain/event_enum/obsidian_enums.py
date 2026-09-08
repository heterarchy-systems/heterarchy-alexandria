"""Enums for Obsidian-backed Alexandria notes."""

from __future__ import annotations

from enum import StrEnum


class AlexandriaNoteType(StrEnum):
    """Managed Alexandria Markdown note kinds."""

    CONTEXT = "context"
    MEMORY_COMPACT = "memory_compact"
    SKILL = "skill"
    PROMPT = "prompt"
    JOB_PLAN = "job_plan"
    IMPLEMENTATION_HISTORY = "implementation_history"


class ObsidianIndexStatus(StrEnum):
    """Index lifecycle status for one vault note."""

    INDEXED = "indexed"
    UNINDEXED = "unindexed"
    STALE = "stale"
    ERROR = "error"


class ObsidianWriteMode(StrEnum):
    """Caller-visible mutation semantics for canonical notes."""

    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class ObsidianWriteMatchBy(StrEnum):
    """Supported exact identity selectors for note writes."""

    NOTE_ID = "note_id"
    PATH = "path"


class ObsidianFrontmatterMode(StrEnum):
    """How caller-owned frontmatter fields are applied on update."""

    MERGE = "merge"
    REPLACE_USER_FIELDS = "replace_user_fields"


class ObsidianWriteOperation(StrEnum):
    """Observed result of one explicit note write."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class ObsidianReportBundleCompletionStatus(StrEnum):
    """Durable completion states for an orchestrated report bundle run."""

    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    PARTIAL_SOURCE_SAVED = "PARTIAL_SOURCE_SAVED"
    PARTIAL_OWNER_UPDATE = "PARTIAL_OWNER_UPDATE"
    PARTIAL_INDEXED = "PARTIAL_INDEXED"
    PARTIAL_GRAPH_UNVERIFIED = "PARTIAL_GRAPH_UNVERIFIED"
    FAILED_NO_MUTATION = "FAILED_NO_MUTATION"


class ObsidianIndexErrorCode(StrEnum):
    """Stable operator-facing error codes for Context note indexing."""

    INVALID_SCOPE = "INVALID_SCOPE"
    MISSING_AGENT_ID = "MISSING_AGENT_ID"
    MISSING_SESSION_ID = "MISSING_SESSION_ID"
    MISSING_PROJECT = "MISSING_PROJECT"
    MISSING_USER_ID = "MISSING_USER_ID"
    INVALID_STATUS = "INVALID_STATUS"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    INVALID_MEMORY_FUNCTION = "INVALID_MEMORY_FUNCTION"
    INVALID_SCOPE_IDENTITY = "INVALID_SCOPE_IDENTITY"
    INVALID_SUPERSEDE = "INVALID_SUPERSEDE"
    INVALID_CONTENT_HASH = "INVALID_CONTENT_HASH"
    INVALID_CONTENT_INTEGRITY = "INVALID_CONTENT_INTEGRITY"
    DUPLICATE_CONTEXT_ID = "DUPLICATE_CONTEXT_ID"
    DUPLICATE_CONTEXT_CONTENT = "DUPLICATE_CONTEXT_CONTENT"
    FRONTMATTER_SECRET_DETECTED = "FRONTMATTER_SECRET_DETECTED"
    FRONTMATTER_PARSE_ERROR = "FRONTMATTER_PARSE_ERROR"
    PATH_SECURITY_VIOLATION = "PATH_SECURITY_VIOLATION"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    INDEX_WRITE_FAILED = "INDEX_WRITE_FAILED"


class ObsidianContextLifecycleStatus(StrEnum):
    """Lifecycle status values accepted for Context recall from Obsidian."""

    ACTIVE = "active"
    CURRENT = "current"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"
    DRAFT = "draft"
    ERROR = "error"
    NEEDS_REVIEW = "needs_review"
    PENDING = "pending"
    PENDING_REVIEW = "pending_review"
    REVIEW = "review"
    REVIEWED = "reviewed"
    STALE = "stale"
    SUPERSEDED = "superseded"

    @classmethod
    def from_frontmatter_text(
        cls,
        value: str,
    ) -> ObsidianContextLifecycleStatus:
        """Normalize frontmatter text into a lifecycle status enum.

        Args:
            value: Raw lifecycle status text.

        Returns:
            Matching lifecycle status enum.
        """
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        return cls(normalized)

    @classmethod
    def default_recall_values(cls) -> tuple[str, ...]:
        """Return status values included in default Context recall.

        Returns:
            Status values that belong in default recall.
        """
        return (cls.ACTIVE.value, cls.CURRENT.value)

    @classmethod
    def default_excluded_values(cls) -> tuple[str, ...]:
        """Return known status values excluded from default Context recall.

        Returns:
            Status values excluded from default recall.
        """
        return tuple(
            status.value
            for status in cls
            if status.value not in cls.default_recall_values()
        )

    def is_default_recall_visible(self) -> bool:
        """Return whether this lifecycle status belongs in default recall.

        Returns:
            True when this status is visible by default.
        """
        return self.value in self.default_recall_values()


class ObsidianRelationType(StrEnum):
    """Supported Alexandria graph relation kinds."""

    CITES = "cites"
    DERIVED_FROM = "derived_from"
    RELATED = "related"
    SUPERSEDES = "supersedes"
    PROMOTES_TO = "promotes_to"
    BLOCKS = "blocks"
    RESOLVES = "resolves"
    DUPLICATES = "duplicates"
    SUPPORTS = "supports"
    EXTENDS = "extends"
    CONTRADICTS = "contradicts"
    CONTAINS = "contains"
    WIKILINK = "wikilink"


class ObsidianEdgeSourceKind(StrEnum):
    """Where an indexed graph edge came from."""

    FRONTMATTER = "frontmatter"
    WIKILINK = "wikilink"
    INFERRED = "inferred"
    USER_APPROVED = "user_approved"
