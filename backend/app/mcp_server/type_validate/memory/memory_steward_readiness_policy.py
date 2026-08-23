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
    manual_review_required: int,
) -> tuple[str, ...]:
    """Return review warnings that block automatic compact refresh apply.

    Args:
        warnings: Readiness warning codes.
        manual_review_required: Count of queue items requiring manual review.

    Returns:
        Review warning codes that require librarian judgment before auto-apply.
    """
    blockers: list[str] = []
    if "vault_review_queue_not_empty" in warnings and manual_review_required > 0:
        blockers.append("vault_manual_review_required")
    if "current_memory_compact_review_blocked" in warnings:
        blockers.append("current_memory_compact_review_blocked")
    return tuple(blockers)
    return ()


def readiness_warnings(
    rag: RagStatusPayload,
    compact: CurrentCompactPayload,
    compact_age_days: int | None,
    max_compact_age_days: int,
    review_total: int,
) -> list[str]:
    """Build deterministic readiness warning codes.

    Args:
        rag: Validated RAG health fields.
        compact: Validated current compact fields.
        compact_age_days: Calculated compact age in days.
        max_compact_age_days: Maximum acceptable compact age.
        review_total: Total review queue count.

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
    if review_total > 0:
        warnings.append("vault_review_queue_not_empty")
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


def readiness_next_actions(
    warnings: list[str],
    auto_move_candidates: int,
    manual_review_required: int,
    review_total: int,
) -> list[JSONObject]:
    """Build deterministic next actions from readiness warnings.

    Args:
        warnings: Readiness warning codes.
        auto_move_candidates: Count of safe auto-move candidates.
        manual_review_required: Count of manual-review candidates.
        review_total: Total review queue count.

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
    if "vault_review_queue_not_empty" in warning_set and auto_move_candidates > 0:
        actions.append(
            {
                "priority": 30,
                "code": "curate_vault_review_queue",
                "tool": "alexandria_vault_review_move_plan",
                "summary": "Plan safe vault moves for automatic review candidates.",
                "dry_run_first": True,
            }
        )
    if "vault_review_queue_not_empty" in warning_set and manual_review_required > 0:
        actions.append(
            {
                "priority": 40,
                "code": "review_manual_vault_queue",
                "tool": "alexandria_vault_review_queue",
                "summary": "Inspect queue items that require human judgment.",
                "dry_run_first": True,
            }
        )
    if (
        "vault_review_queue_not_empty" in warning_set
        and review_total > 0
        and auto_move_candidates == 0
        and manual_review_required == 0
    ):
        actions.append(
            {
                "priority": 30,
                "code": "inspect_vault_review_queue",
                "tool": "alexandria_vault_review_queue",
                "summary": "Inspect review queue candidates before planning curation.",
                "dry_run_first": True,
            }
        )
    return actions
