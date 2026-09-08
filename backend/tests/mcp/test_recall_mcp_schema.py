"""MCP schema parity for the high-level recall tool."""

from __future__ import annotations

import anyio

from app.mcp_server.server_runtime import build_mcp_server


def test_recall_mcp_tool_exposes_typed_request_and_response_schema() -> None:
    """The MCP tool must publish both its nested request and Recall response schema."""
    tools = anyio.run(build_mcp_server().list_tools)
    recall = next(tool for tool in tools if tool.name == "alexandria_recall")
    assert recall.input_schema["properties"]["request"]["$ref"].endswith(
        "RecallRequestSchema"
    )
    assert recall.output_schema is not None
    assert set(recall.output_schema["properties"]) >= {
        "outcome",
        "matches",
        "trace",
        "warnings",
    }
