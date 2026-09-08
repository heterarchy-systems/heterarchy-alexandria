"""Readiness warning and next-action policy helpers."""

from __future__ import annotations

from app.mcp_server.type_validate.memory.memory_steward_readiness_schemas import (
    CurrentCompactPayload,
    RagStatusPayload,
)
from app.shared.types.extra_types import JSONObject

COMPACT_REFRESH_WARNINGS = frozenset(
    {
        "current_memory_compact_missing",
        "current_memory_compact_stale",
        "current_memory_compact_timestamp_missing",
        "current_memory_compact_review_blocked",
        "current_memory_compact_review_needs_revision",
    }
)
RAG_HEALTH_WARNINGS = frozenset(
    {
        "rag_fts_not_healthy",
        "rag_vector_not_healthy",
        "rag_embedding_not_healthy",
        "rag_status_warnings_present",
        "rag_status_unavailable",
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
    if "current_memory_compact_review_blocked" in warnings:
        return ("current_memory_compact_review_blocked",)
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
    if rag.fts != "HEALTHY":
        warnings.append("rag_fts_not_healthy")
    if rag.vector != "HEALTHY":
        warnings.append("rag_vector_not_healthy")
    if rag.embedding != "HEALTHY":
        warnings.append("rag_embedding_not_healthy")
    if rag.warnings:
        warnings.append("rag_status_warnings_present")
    if not compact.id:
        warnings.append("current_memory_compact_missing")
    elif compact.has_source_hash_mismatch():
        warnings.append("current_memory_compact_stale")
    elif _compact_timestamp_missing(compact) or compact_age_days is None:
        warnings.append("current_memory_compact_timestamp_missing")
    elif compact_age_days > max_compact_age_days:
        warnings.append("current_memory_compact_stale")
    return warnings


def _compact_timestamp_missing(compact: CurrentCompactPayload) -> bool:
    """Execute compact timestamp missing.

    Args:
        compact: Compact used by this operation.

    Returns:
        Whether compact timestamp missing.
    """
    return any(
        warning
        in {
            "memory_compact_timestamp_missing",
            "current_memory_compact_timestamp_missing",
        }
        for warning in compact.warnings
    )


def readiness_next_actions(warnings: list[str]) -> list[JSONObject]:
    """Build deterministic next actions from readiness warnings.

    Args:
        warnings: Readiness warning codes.

    Returns:
        JSON next-action objects ordered by priority.
    """
    warning_set = set(warnings)
    actions: list[JSONObject] = []
    if {
        "rag_fts_not_healthy",
        "rag_vector_not_healthy",
        "rag_embedding_not_healthy",
        "rag_status_warnings_present",
        "rag_status_unavailable",
    } & warning_set:
        actions.append(
            {
                "priority": 10,
                "code": "repair_rag_index",
                "tool": "alexandria_reindex_vault",
                "summary": "Repair or rebuild retrieval indexes before trusting answers.",
                "dry_run_first": False,
            }
        )
    if COMPACT_REFRESH_WARNINGS & warning_set:
        actions.append(
            {
                "priority": 20,
                "code": "refresh_current_memory_compact",
                "tool": "alexandria_memory_steward_refresh_current_compact",
                "summary": "Refresh the CURRENT Memory Compact from readiness evidence.",
                "dry_run_first": True,
            }
        )
    return actions
