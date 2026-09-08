"""Summary and status views over validated maintenance CLI payloads."""

from __future__ import annotations

from app.cli.type_validate.maintenance_payload_schemas import (
    CurrentCompactReviewPayload,
    MaintenanceCheckSummaryPayload,
    NextActionPayload,
    validate_combined_check_payload,
    validate_mcp_smoke_payload,
    validate_preflight_payload,
)
from app.shared.types.extra_types import JSONValue


def check_summary(mcp_smoke: JSONValue, preflight: JSONValue) -> JSONValue:
    """Return a compact combined MCP/preflight status payload.

    Args:
        mcp_smoke: MCP smoke-check payload.
        preflight: Memory Steward preflight payload.

    Returns:
        JSON-compatible summary payload.
    """
    smoke_payload = validate_mcp_smoke_payload(mcp_smoke)
    preflight_payload = validate_preflight_payload(preflight)
    readiness = preflight_payload.current_readiness()
    current_compact = readiness.current_memory_compact
    compact_review = (
        readiness.current_memory_compact_review or CurrentCompactReviewPayload()
    )
    rag = readiness.rag
    created_compact_id = (
        preflight_payload.created.id if preflight_payload.created is not None else None
    )
    next_action = (
        readiness.next_actions[0] if readiness.next_actions else NextActionPayload()
    )
    summary = MaintenanceCheckSummaryPayload(
        ok=smoke_payload.ok and readiness.ready is True,
        mcp_url=smoke_payload.mcp_url,
        mcp_tool_count=smoke_payload.tool_count,
        mcp_required_tools_count=len(smoke_payload.required_tools),
        mcp_required_tools=smoke_payload.required_tools,
        mcp_missing_tools=smoke_payload.missing_tools,
        preflight_status=preflight_payload.status,
        refresh_required=preflight_payload.refresh_required,
        created=created_compact_id is not None,
        created_compact_id=created_compact_id,
        ready=readiness.ready,
        warnings=readiness.warnings,
        current_compact_id=current_compact.id,
        compact_age_days=current_compact.age_days,
        max_compact_age_days=current_compact.max_age_days,
        rag_fts=rag.fts,
        rag_vector=rag.vector,
        rag_embedding=rag.embedding,
        current_compact_review_verdict=compact_review.verdict,
        current_compact_review_total_score=compact_review.total_score,
        current_compact_review_max_score=compact_review.max_score,
        current_compact_review_recommended_actions=compact_review.recommended_actions,
        next_actions_count=len(readiness.next_actions),
        next_action=next_action.code,
        next_action_tool=next_action.tool,
    )
    return summary.model_dump(mode="json")


def check_ok(payload: JSONValue) -> bool:
    """Return whether a combined check payload is healthy."""
    return validate_combined_check_payload(payload).ok is True


def mcp_smoke_ok(payload: JSONValue) -> bool:
    """Return whether an MCP smoke payload is healthy."""
    return validate_mcp_smoke_payload(payload).ok is True


def preflight_ready(payload: JSONValue) -> bool:
    """Return whether a preflight payload reports ready Memory Steward state."""
    return validate_preflight_payload(payload).current_readiness().ready is True
