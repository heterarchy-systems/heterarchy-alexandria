"""Memory Compact enum definitions."""

from __future__ import annotations

from enum import StrEnum


class MemoryCompactStatus(StrEnum):
    """Lifecycle state for one Memory Compact."""

    DRAFT = "DRAFT"
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class MemoryCompactReviewVerdict(StrEnum):
    """Quality review verdict for Memory Compact gates."""

    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class MemoryStewardReadinessWarningCode(StrEnum):
    """Readiness warning codes for Memory Compact freshness and RAG health gates."""

    CURRENT_MEMORY_COMPACT_MISSING = "current_memory_compact_missing"
    CURRENT_MEMORY_COMPACT_STALE = "current_memory_compact_stale"
    CURRENT_MEMORY_COMPACT_TIMESTAMP_MISSING = (
        "current_memory_compact_timestamp_missing"
    )
    MEMORY_COMPACT_TIMESTAMP_MISSING = "memory_compact_timestamp_missing"
    MEMORY_COMPACT_STALE = "memory_compact_stale"
    CURRENT_MEMORY_COMPACT_REVIEW_BLOCKED = "current_memory_compact_review_blocked"
    CURRENT_MEMORY_COMPACT_REVIEW_NEEDS_REVISION = (
        "current_memory_compact_review_needs_revision"
    )
    RAG_FTS_NOT_HEALTHY = "rag_fts_not_healthy"
    RAG_VECTOR_NOT_HEALTHY = "rag_vector_not_healthy"
    RAG_EMBEDDING_NOT_HEALTHY = "rag_embedding_not_healthy"
    RAG_EMBEDDING_REINDEX_REQUIRED = "rag_embedding_reindex_required"
    RAG_STATUS_WARNINGS_PRESENT = "rag_status_warnings_present"
    RAG_STATUS_UNAVAILABLE = "rag_status_unavailable"


class MemoryCompactRefreshStatus(StrEnum):
    """Outcome status for a Memory Steward CURRENT compact refresh operation."""

    UP_TO_DATE = "up_to_date"
    REFRESH_REQUIRED = "refresh_required"
    BLOCKED_BY_RAG_HEALTH = "blocked_by_rag_health"
    BLOCKED_BY_COMPACT_REVIEW = "blocked_by_compact_review"
    DRAFT_CREATED = "draft_created"
    REFRESHED = "refreshed"
