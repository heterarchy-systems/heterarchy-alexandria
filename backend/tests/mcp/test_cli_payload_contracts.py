"""CLI Pydantic payload contract tests."""

from __future__ import annotations

from app.cli.type_validate.maintenance_payload_views import (
    check_summary,
    preflight_ready,
)
from app.cli.type_validate.mcp_protocol_payload_contracts import mcp_tool_names


def test_check_summary_defaults_missing_nested_payloads_to_not_ready() -> None:
    """Check summaries should not treat absent readiness evidence as healthy."""
    summary = check_summary(
        {"ok": True, "required_tools": ["tool-a"]},
        {"status": "missing-readiness"},
    )

    assert summary["ok"] is False
    assert summary["ready"] is None
    assert summary["mcp_required_tools_count"] == 1
    assert summary["warnings"] == []
    assert summary["next_actions_count"] == 0


def test_preflight_ready_uses_post_refresh_readiness_before_direct_readiness() -> None:
    """Preflight readiness should prefer post-refresh evidence."""
    payload = {
        "readiness": {"ready": True},
        "post_refresh_readiness": {"ready": False},
    }

    assert preflight_ready(payload) is False


def test_mcp_tool_names_uses_validated_tool_objects_only() -> None:
    """MCP tools/list parsing should ignore malformed tool entries."""
    payload = {
        "result": {
            "tools": [
                {"name": "alexandria_memory_steward_readiness"},
                {"title": "missing name"},
                "not-an-object",
            ]
        }
    }

    assert mcp_tool_names(payload) == {"alexandria_memory_steward_readiness"}
