"""Readiness warning and next-action policy helpers."""

from __future__ import annotations

from app.mcp_server.type_validate.memory.memory_steward_readiness_schemas import (
    CurrentCompactPayload,
    NextActionPayload,
    RagStatusPayload,
)
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryStewardReadinessWarningCode,
)

COMPACT_REFRESH_WARNINGS: frozenset[MemoryStewardReadinessWarningCode] = frozenset(
    {
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_MISSING,
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_STALE,
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_TIMESTAMP_MISSING,
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_REVIEW_BLOCKED,
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_REVIEW_NEEDS_REVISION,
    }
)
RAG_HEALTH_WARNINGS: frozenset[MemoryStewardReadinessWarningCode] = frozenset(
    {
        MemoryStewardReadinessWarningCode.RAG_FTS_NOT_HEALTHY,
        MemoryStewardReadinessWarningCode.RAG_VECTOR_NOT_HEALTHY,
        MemoryStewardReadinessWarningCode.RAG_EMBEDDING_NOT_HEALTHY,
        MemoryStewardReadinessWarningCode.RAG_EMBEDDING_REINDEX_REQUIRED,
        MemoryStewardReadinessWarningCode.RAG_STATUS_WARNINGS_PRESENT,
        MemoryStewardReadinessWarningCode.RAG_STATUS_UNAVAILABLE,
    }
)
_TIMESTAMP_MISSING_WARNINGS: frozenset[MemoryStewardReadinessWarningCode] = frozenset(
    {
        MemoryStewardReadinessWarningCode.MEMORY_COMPACT_TIMESTAMP_MISSING,
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_TIMESTAMP_MISSING,
    }
)


def needs_current_compact_refresh(warnings: tuple[str, ...]) -> bool:
    """Return whether warnings require a CURRENT compact refresh.

    Args:
        warnings: Readiness warning codes.

    Returns:
        True when compact freshness warnings are present.
    """
    return any(warning in COMPACT_REFRESH_WARNINGS for warning in warnings)


def rag_health_blocking_warnings(warnings: tuple[str, ...]) -> tuple[str, ...]:
    """Return RAG warnings that block CURRENT compact refresh apply.

    Args:
        warnings: Readiness warning codes.

    Returns:
        RAG warning codes that require repair before compact refresh.
    """
    return tuple(warning for warning in warnings if warning in RAG_HEALTH_WARNINGS)


def review_blocking_warnings(
    warnings: tuple[str, ...],
) -> tuple[str, ...]:
    """Return compact-review warnings that block automatic refresh apply.

    Args:
        warnings: Readiness warning codes.

    Returns:
        Compact quality-review warnings that require explicit repair.
    """
    if (
        MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_REVIEW_BLOCKED.value
        in warnings
    ):
        return (
            MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_REVIEW_BLOCKED.value,
        )
    return ()


def readiness_warnings(
    rag: RagStatusPayload,
    compact: CurrentCompactPayload,
    compact_age_days: int | None,
    max_compact_age_days: int,
) -> list[str]:
    """Build deterministic readiness warning codes.

    Args:
        rag: Validated RAG health fields.
        compact: Validated current compact fields.
        compact_age_days: Calculated compact age in days.
        max_compact_age_days: Maximum acceptable compact age.

    Returns:
        Readiness warning codes.
    """
    warnings: list[str] = []
    if rag.fts != RagHealthState.HEALTHY:
        warnings.append(MemoryStewardReadinessWarningCode.RAG_FTS_NOT_HEALTHY.value)
    if rag.vector != RagHealthState.HEALTHY:
        warnings.append(MemoryStewardReadinessWarningCode.RAG_VECTOR_NOT_HEALTHY.value)
    if rag.embedding != RagHealthState.HEALTHY:
        warnings.append(
            MemoryStewardReadinessWarningCode.RAG_EMBEDDING_NOT_HEALTHY.value
        )
    if rag.warnings:
        warnings.append(
            MemoryStewardReadinessWarningCode.RAG_STATUS_WARNINGS_PRESENT.value
        )
    if not compact.id:
        warnings.append(
            MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_MISSING.value
        )
    elif compact.has_source_hash_mismatch():
        warnings.append(
            MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_STALE.value
        )
    elif (
        any(warning in _TIMESTAMP_MISSING_WARNINGS for warning in compact.warnings)
        or compact_age_days is None
    ):
        warnings.append(
            MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_TIMESTAMP_MISSING.value
        )
    elif compact_age_days > max_compact_age_days:
        warnings.append(
            MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_STALE.value
        )
    return warnings


def readiness_next_actions(warnings: list[str]) -> list[NextActionPayload]:
    """Build deterministic next actions from readiness warnings.

    Args:
        warnings: Readiness warning codes.

    Returns:
        Validated NextActionPayload items ordered by priority.
    """
    warning_set = set(warnings)
    actions: list[NextActionPayload] = []
    if RAG_HEALTH_WARNINGS & warning_set:
        actions.append(
            NextActionPayload(
                priority=10,
                code="repair_rag_index",
                tool="alexandria_reindex_vault",
                summary="Repair or rebuild retrieval indexes before trusting answers.",
                dry_run_first=False,
            )
        )
    if COMPACT_REFRESH_WARNINGS & warning_set:
        actions.append(
            NextActionPayload(
                priority=20,
                code="refresh_current_memory_compact",
                tool="alexandria_memory_steward_refresh_current_compact",
                summary="Refresh the CURRENT Memory Compact from readiness evidence.",
                dry_run_first=True,
            )
        )
    return actions
