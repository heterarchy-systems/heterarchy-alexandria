"""Read-only end-to-end benchmark for the public Context RAG search API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from time import perf_counter_ns

import httpx

SEARCH_PATH = "/memory/contexts/retrieval/search"
RAG_STATUS_PATH = "/memory/contexts/rag/status"
DEFAULT_TOKEN_ENV = "ALEXANDRIA_BENCHMARK_BEARER_TOKEN"
DEFAULT_QUERIES = (
    "Graph-aware Context Retrieval",
    "heterarchy-alexandria retrieval architecture",
    "Evidence Intelligence Morning Read",
    "Memory reconciliation graph integrity",
)
STRATEGIES = ("FTS_ONLY", "VECTOR_ONLY", "HYBRID")


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Validated command-line configuration for one benchmark run."""

    base_url: str
    queries: tuple[str, ...]
    strategies: tuple[str, ...]
    project: str | None
    limit: int
    warmups: int
    repetitions: int
    timeout_seconds: float
    token_env: str
    output_path: Path | None


@dataclass(frozen=True, slots=True)
class SearchObservation:
    """One successful HTTP search observation."""

    elapsed_ms: float
    status_code: int
    effective_strategy: str | None
    match_count: int
    warning_count: int
    graph_evidence_match_count: int
    response_bytes: int


@dataclass(frozen=True, slots=True)
class CaseSummary:
    """Aggregated observations for one query and requested strategy."""

    query: str
    requested_strategy: str
    successful_samples: int
    failed_samples: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_mean_ms: float | None
    latency_min_ms: float | None
    latency_max_ms: float | None
    response_bytes_p50: int | None
    match_count_min: int | None
    match_count_max: int | None
    warning_count_max: int | None
    graph_evidence_match_count_max: int | None
    effective_strategies: tuple[str, ...]
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironment:
    """Execution environment recorded with the benchmark result."""

    measured_at: str
    python_version: str
    platform: str
    base_url: str
    project: str | None
    limit: int
    warmups: int
    repetitions: int
    graph_phase_timing_available: bool
    server_memory_timing_available: bool


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Serializable benchmark report."""

    environment: BenchmarkEnvironment
    rag_status: object
    cases: tuple[CaseSummary, ...]


def _parse_args() -> BenchmarkConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the running Alexandria Context RAG HTTP endpoint without "
            "mutating Vault or index data."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument(
        "--strategy",
        action="append",
        choices=STRATEGIES,
        dest="strategies",
    )
    parser.add_argument("--project")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--output", type=Path, dest="output_path")
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 50:
        parser.error("--limit must be between 1 and 50")
    if args.warmups < 0:
        parser.error("--warmups must be zero or greater")
    if args.repetitions < 1:
        parser.error("--repetitions must be one or greater")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")

    queries = tuple(args.queries or DEFAULT_QUERIES)
    strategies = tuple(args.strategies or STRATEGIES)
    return BenchmarkConfig(
        base_url=args.base_url.rstrip("/"),
        queries=queries,
        strategies=strategies,
        project=args.project,
        limit=args.limit,
        warmups=args.warmups,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout_seconds,
        token_env=args.token_env,
        output_path=args.output_path,
    )


def _request_headers(token_env: str) -> dict[str, str]:
    token = os.getenv(token_env)
    if token is None or not token.strip():
        return {}
    return {"Authorization": f"Bearer {token.strip()}"}


def _search_payload(
    config: BenchmarkConfig, query: str, strategy: str
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": query,
        "strategy": strategy,
        "limit": config.limit,
    }
    if config.project is not None:
        payload["project"] = config.project
    return payload


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("response payload must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _graph_evidence_match_count(matches: list[object]) -> int:
    count = 0
    for raw_match in matches:
        if not isinstance(raw_match, dict):
            continue
        graph_evidence = raw_match.get("graph_evidence")
        if isinstance(graph_evidence, list) and graph_evidence:
            count += 1
    return count


async def _observe_search(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    query: str,
    strategy: str,
) -> SearchObservation:
    started_ns = perf_counter_ns()
    response = await client.post(
        SEARCH_PATH,
        json=_search_payload(config, query, strategy),
    )
    elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
    if response.is_error:
        detail = " ".join(response.text.split())[:240]
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")

    payload: object = response.json()
    response_mapping = _mapping(payload)
    matches = _sequence(response_mapping.get("matches"))
    warnings = _sequence(response_mapping.get("warnings"))
    return SearchObservation(
        elapsed_ms=elapsed_ms,
        status_code=response.status_code,
        effective_strategy=_optional_string(response_mapping.get("effective_strategy")),
        match_count=len(matches),
        warning_count=len(warnings),
        graph_evidence_match_count=_graph_evidence_match_count(matches),
        response_bytes=len(response.content),
    )


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = max(0, ceil(len(ordered) * ratio) - 1)
    return ordered[index]


def _summarize_case(
    query: str,
    strategy: str,
    observations: list[SearchObservation],
    failures: list[str],
) -> CaseSummary:
    if not observations:
        return CaseSummary(
            query=query,
            requested_strategy=strategy,
            successful_samples=0,
            failed_samples=len(failures),
            latency_p50_ms=None,
            latency_p95_ms=None,
            latency_mean_ms=None,
            latency_min_ms=None,
            latency_max_ms=None,
            response_bytes_p50=None,
            match_count_min=None,
            match_count_max=None,
            warning_count_max=None,
            graph_evidence_match_count_max=None,
            effective_strategies=(),
            failures=tuple(failures),
        )

    latencies = [observation.elapsed_ms for observation in observations]
    response_sizes = sorted(observation.response_bytes for observation in observations)
    middle = len(response_sizes) // 2
    response_bytes_p50 = response_sizes[middle]
    effective_strategies = tuple(
        sorted(
            {
                observation.effective_strategy
                for observation in observations
                if observation.effective_strategy is not None
            }
        )
    )
    return CaseSummary(
        query=query,
        requested_strategy=strategy,
        successful_samples=len(observations),
        failed_samples=len(failures),
        latency_p50_ms=round(_percentile(latencies, 0.50), 3),
        latency_p95_ms=round(_percentile(latencies, 0.95), 3),
        latency_mean_ms=round(statistics.fmean(latencies), 3),
        latency_min_ms=round(min(latencies), 3),
        latency_max_ms=round(max(latencies), 3),
        response_bytes_p50=response_bytes_p50,
        match_count_min=min(item.match_count for item in observations),
        match_count_max=max(item.match_count for item in observations),
        warning_count_max=max(item.warning_count for item in observations),
        graph_evidence_match_count_max=max(
            item.graph_evidence_match_count for item in observations
        ),
        effective_strategies=effective_strategies,
        failures=tuple(failures),
    )


async def _benchmark_case(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    query: str,
    strategy: str,
) -> CaseSummary:
    for _ in range(config.warmups):
        try:
            await _observe_search(client, config, query, strategy)
        except (httpx.HTTPError, RuntimeError, ValueError):
            break

    observations: list[SearchObservation] = []
    failures: list[str] = []
    for _ in range(config.repetitions):
        try:
            observation = await _observe_search(client, config, query, strategy)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        else:
            observations.append(observation)
    return _summarize_case(query, strategy, observations, failures)


async def _read_rag_status(client: httpx.AsyncClient) -> object:
    response = await client.get(RAG_STATUS_PATH)
    if response.is_error:
        detail = " ".join(response.text.split())[:240]
        return {"status_code": response.status_code, "error": detail}
    return response.json()


async def _run(config: BenchmarkConfig) -> BenchmarkReport:
    timeout = httpx.Timeout(config.timeout_seconds)
    async with httpx.AsyncClient(
        base_url=config.base_url,
        timeout=timeout,
        headers=_request_headers(config.token_env),
    ) as client:
        rag_status = await _read_rag_status(client)
        cases = [
            await _benchmark_case(client, config, query, strategy)
            for query in config.queries
            for strategy in config.strategies
        ]

    environment = BenchmarkEnvironment(
        measured_at=datetime.now(UTC).isoformat(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        base_url=config.base_url,
        project=config.project,
        limit=config.limit,
        warmups=config.warmups,
        repetitions=config.repetitions,
        graph_phase_timing_available=False,
        server_memory_timing_available=False,
    )
    return BenchmarkReport(
        environment=environment,
        rag_status=rag_status,
        cases=tuple(cases),
    )


def main() -> None:
    """Run the benchmark and emit one deterministic JSON report."""
    config = _parse_args()
    report = asyncio.run(_run(config))
    rendered = json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(f"{rendered}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
