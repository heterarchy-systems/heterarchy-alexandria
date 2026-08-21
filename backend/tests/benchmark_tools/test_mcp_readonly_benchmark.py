"""Contract tests for the read-only MCP v2 benchmark."""

from __future__ import annotations

import pytest
from benchmarks.mcp_readonly_benchmark import (
    OperationObservation,
    _failure_message,
    _parse_tool_arguments,
    _summarize_operation,
    _tool_result_size,
)

from mcp import types


def test_parse_tool_arguments_requires_a_json_object() -> None:
    """Tool arguments should retain object shape and reject scalar roots."""
    assert _parse_tool_arguments('{"limit": 5, "enabled": true}') == {
        "limit": 5,
        "enabled": True,
    }
    with pytest.raises(ValueError, match="must be a JSON object"):
        _parse_tool_arguments("[1, 2]")


def test_summarize_operation_reports_latency_size_and_failures() -> None:
    """Operation summaries should retain samples without performance thresholds."""
    summary = _summarize_operation(
        "call_tool",
        [
            OperationObservation(elapsed_ms=10.0, result_size=1),
            OperationObservation(elapsed_ms=20.0, result_size=3),
        ],
        ["RuntimeError: transient"],
    )

    assert summary.successful_samples == 2
    assert summary.failed_samples == 1
    assert summary.latency_p50_ms == 10.0
    assert summary.latency_p95_ms == 20.0
    assert summary.result_size_min == 1
    assert summary.result_size_max == 3
    assert summary.failures == ("RuntimeError: transient",)


def test_tool_result_size_accepts_success_and_rejects_error_results() -> None:
    """The benchmark should count successful content and fail on isError results."""
    success = types.CallToolResult(
        content=[types.TextContent(text="ok"), types.TextContent(text="ready")]
    )
    failure = types.CallToolResult(
        content=[types.TextContent(text="failed")],
        isError=True,
    )

    assert _tool_result_size(success) == 2
    with pytest.raises(RuntimeError, match="isError=true"):
        _tool_result_size(failure)
    with pytest.raises(RuntimeError, match="unexpected tool result type"):
        _tool_result_size(object())


def test_failure_message_unwraps_nested_exception_groups() -> None:
    """Task-group wrappers should preserve the actionable transport failure."""
    failure = ExceptionGroup(
        "transport",
        [ExceptionGroup("nested", [RuntimeError("HTTP 401 Unauthorized")])],
    )

    assert _failure_message(failure) == (
        "ExceptionGroup: RuntimeError: HTTP 401 Unauthorized"
    )
