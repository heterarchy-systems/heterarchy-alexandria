"""Read-only latency benchmark for the official Alexandria MCP v2 surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import httpx2
from mcp.client.streamable_http import streamable_http_client

from benchmarks.benchmark_statistics import summarize_latencies
from mcp import ClientSession, types

DEFAULT_ENDPOINT = "http://127.0.0.1:8000/mcp"
DEFAULT_TOKEN_ENV = "ALEXANDRIA_BENCHMARK_BEARER_TOKEN"
DEFAULT_TOOL_NAME = "alexandria_rag_status"


@dataclass(frozen=True, slots=True)
class McpBenchmarkConfig:
    """Validated configuration for one read-only MCP benchmark run."""

    endpoint_url: str
    token_env: str
    tool_name: str
    tool_arguments: dict[str, object]
    warmups: int
    repetitions: int
    timeout_seconds: float
    output_path: Path | None


@dataclass(frozen=True, slots=True)
class OperationObservation:
    """One successful operation latency and bounded result-size observation."""

    elapsed_ms: float
    result_size: int


@dataclass(frozen=True, slots=True)
class OperationSummary:
    """Latency and failure summary for one MCP operation."""

    operation: str
    successful_samples: int
    failed_samples: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_mean_ms: float | None
    latency_min_ms: float | None
    latency_max_ms: float | None
    result_size_min: int | None
    result_size_max: int | None
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class McpBenchmarkEnvironment:
    """Execution environment recorded with an MCP benchmark report."""

    measured_at: str
    python_version: str
    platform: str
    endpoint_url: str
    warmups: int
    repetitions: int
    token_env: str
    bearer_token_present: bool


@dataclass(frozen=True, slots=True)
class McpBenchmarkReport:
    """Machine-readable MCP v2 benchmark result."""

    environment: McpBenchmarkEnvironment
    protocol_version: str | None
    server_name: str | None
    server_version: str | None
    tool_name: str
    transport_connect: OperationSummary
    initialize: OperationSummary
    list_tools: OperationSummary
    call_tool: OperationSummary


def _parse_args() -> McpBenchmarkConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Measure MCP v2 transport, initialize, tools/list, and one read-only "
            "tools/call operation."
        )
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--tool-name", default=DEFAULT_TOOL_NAME)
    parser.add_argument(
        "--tool-arguments",
        default="{}",
        help="JSON object passed to the selected read-only tool.",
    )
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, dest="output_path")
    args = parser.parse_args()

    if args.warmups < 0:
        parser.error("--warmups must be zero or greater")
    if args.repetitions < 1:
        parser.error("--repetitions must be one or greater")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if not args.tool_name.strip():
        parser.error("--tool-name must not be blank")
    try:
        tool_arguments = _parse_tool_arguments(args.tool_arguments)
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(f"invalid --tool-arguments value: {exc}")

    return McpBenchmarkConfig(
        endpoint_url=args.endpoint.rstrip("/"),
        token_env=args.token_env,
        tool_name=args.tool_name.strip(),
        tool_arguments=tool_arguments,
        warmups=args.warmups,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout_seconds,
        output_path=args.output_path,
    )


def _parse_tool_arguments(value: str) -> dict[str, object]:
    """Parse one bounded JSON object for a read-only MCP tool call.

    Args:
        value: JSON text supplied on the command line.

    Returns:
        String-keyed tool arguments.

    Raises:
        ValueError: If the JSON root is not an object.
    """
    parsed: object = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return {str(key): item for key, item in parsed.items()}


def _request_headers(token_env: str) -> dict[str, str]:
    token = os.getenv(token_env)
    if token is None or not token.strip():
        return {}
    return {"Authorization": f"Bearer {token.strip()}"}


def _summarize_operation(
    operation: str,
    observations: list[OperationObservation],
    failures: list[str],
) -> OperationSummary:
    latency = summarize_latencies(tuple(item.elapsed_ms for item in observations))
    result_sizes = tuple(item.result_size for item in observations)
    return OperationSummary(
        operation=operation,
        successful_samples=len(observations),
        failed_samples=len(failures),
        latency_p50_ms=latency.p50_ms,
        latency_p95_ms=latency.p95_ms,
        latency_mean_ms=latency.mean_ms,
        latency_min_ms=latency.min_ms,
        latency_max_ms=latency.max_ms,
        result_size_min=min(result_sizes) if result_sizes else None,
        result_size_max=max(result_sizes) if result_sizes else None,
        failures=tuple(failures),
    )


async def _measure_operation(
    operation: str,
    sample: Callable[[], Awaitable[int]],
    warmups: int,
    repetitions: int,
) -> OperationSummary:
    for _ in range(warmups):
        try:
            await sample()
        except Exception:
            break

    observations: list[OperationObservation] = []
    failures: list[str] = []
    for _ in range(repetitions):
        started_ns = perf_counter_ns()
        try:
            result_size = await sample()
        except Exception as exc:
            failures.append(_failure_message(exc))
        else:
            observations.append(
                OperationObservation(
                    elapsed_ms=(perf_counter_ns() - started_ns) / 1_000_000,
                    result_size=result_size,
                )
            )
    return _summarize_operation(operation, observations, failures)


def _single_observation_summary(
    operation: str,
    elapsed_ms: float,
    result_size: int,
) -> OperationSummary:
    return _summarize_operation(
        operation,
        [OperationObservation(elapsed_ms=elapsed_ms, result_size=result_size)],
        [],
    )


def _failure_message(exc: BaseException) -> str:
    """Return actionable leaf errors from nested task-group failures.

    Args:
        exc: Raised benchmark exception.

    Returns:
        Bounded human-readable failure evidence.
    """
    if not isinstance(exc, BaseExceptionGroup):
        return f"{type(exc).__name__}: {exc}"
    leaves: list[str] = []
    pending = list(exc.exceptions)
    while pending and len(leaves) < 5:
        current = pending.pop(0)
        if isinstance(current, BaseExceptionGroup):
            pending[0:0] = current.exceptions
            continue
        leaves.append(f"{type(current).__name__}: {current}")
    return f"{type(exc).__name__}: " + " | ".join(leaves)


def _failed_operation_summary(operation: str, exc: Exception) -> OperationSummary:
    return _summarize_operation(
        operation,
        [],
        [_failure_message(exc)],
    )


async def _list_tools_sample(session: ClientSession) -> int:
    result = await session.list_tools()
    return len(result.tools)


def _tool_result_size(result: object) -> int:
    """Return successful tool content size and reject protocol errors.

    Args:
        result: MCP tools/call result.

    Returns:
        Number of content blocks in a successful result.

    Raises:
        RuntimeError: If the result type or protocol status is invalid.
    """
    if not isinstance(result, types.CallToolResult):
        raise RuntimeError(f"unexpected tool result type: {type(result).__name__}")
    if result.is_error:
        raise RuntimeError("MCP tool returned isError=true")
    return len(result.content)


async def _call_tool_sample(
    session: ClientSession,
    tool_name: str,
    tool_arguments: dict[str, object],
) -> int:
    result = await session.call_tool(tool_name, tool_arguments)
    return _tool_result_size(result)


async def _run(config: McpBenchmarkConfig) -> McpBenchmarkReport:
    request_headers = _request_headers(config.token_env)
    environment = McpBenchmarkEnvironment(
        measured_at=datetime.now(UTC).isoformat(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        endpoint_url=config.endpoint_url,
        warmups=config.warmups,
        repetitions=config.repetitions,
        token_env=config.token_env,
        bearer_token_present=bool(request_headers),
    )
    transport_summary = _summarize_operation("transport_connect", [], [])
    initialize_summary = _summarize_operation("initialize", [], [])
    list_tools_summary = _summarize_operation("list_tools", [], [])
    call_tool_summary = _summarize_operation("call_tool", [], [])
    protocol_version: str | None = None
    server_name: str | None = None
    server_version: str | None = None

    timeout = httpx2.Timeout(config.timeout_seconds)
    try:
        async with httpx2.AsyncClient(
            headers=request_headers,
            timeout=timeout,
        ) as http_client:
            transport_started_ns = perf_counter_ns()
            async with streamable_http_client(
                config.endpoint_url,
                http_client=http_client,
            ) as (read_stream, write_stream):
                transport_summary = _single_observation_summary(
                    "transport_connect",
                    (perf_counter_ns() - transport_started_ns) / 1_000_000,
                    1,
                )
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=config.timeout_seconds,
                ) as session:
                    initialize_started_ns = perf_counter_ns()
                    initialize_result = await session.initialize()
                    initialize_summary = _single_observation_summary(
                        "initialize",
                        (perf_counter_ns() - initialize_started_ns) / 1_000_000,
                        1,
                    )
                    protocol_version = initialize_result.protocol_version
                    server_name = initialize_result.server_info.name
                    server_version = initialize_result.server_info.version
                    list_tools_summary = await _measure_operation(
                        "list_tools",
                        lambda: _list_tools_sample(session),
                        config.warmups,
                        config.repetitions,
                    )
                    call_tool_summary = await _measure_operation(
                        "call_tool",
                        lambda: _call_tool_sample(
                            session,
                            config.tool_name,
                            config.tool_arguments,
                        ),
                        config.warmups,
                        config.repetitions,
                    )
    except Exception as exc:
        if transport_summary.successful_samples == 0:
            transport_summary = _failed_operation_summary("transport_connect", exc)
        elif initialize_summary.successful_samples == 0:
            initialize_summary = _failed_operation_summary("initialize", exc)
        elif list_tools_summary.successful_samples == 0:
            list_tools_summary = _failed_operation_summary("list_tools", exc)
        elif call_tool_summary.successful_samples == 0:
            call_tool_summary = _failed_operation_summary("call_tool", exc)

    return McpBenchmarkReport(
        environment=environment,
        protocol_version=protocol_version,
        server_name=server_name,
        server_version=server_version,
        tool_name=config.tool_name,
        transport_connect=transport_summary,
        initialize=initialize_summary,
        list_tools=list_tools_summary,
        call_tool=call_tool_summary,
    )


def main() -> None:
    """Run the MCP v2 benchmark and emit one machine-readable JSON report."""
    config = _parse_args()
    report = asyncio.run(_run(config))
    rendered = json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(f"{rendered}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
