"""Read-only end-to-end benchmark for the public Context RAG search API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import httpx

from benchmarks.context_rag_benchmark_contracts import (
    BenchmarkConfig,
    BenchmarkEnvironment,
    BenchmarkQuery,
    BenchmarkReport,
    CaseSummary,
    SearchObservation,
)
from benchmarks.context_rag_benchmark_quality import (
    load_golden_queries,
    retrieved_context_ids,
    retrieved_titles,
    summarize_case,
    summarize_strategy_quality,
)

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
    parser.add_argument(
        "--golden-cases",
        type=Path,
        help=(
            "Optional JSON file containing schema_version=1 and accepted "
            "Context ids or Obsidian titles."
        ),
    )
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 50:
        parser.error("--limit must be between 1 and 50")
    if args.warmups < 0:
        parser.error("--warmups must be zero or greater")
    if args.repetitions < 1:
        parser.error("--repetitions must be one or greater")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if args.golden_cases is not None and args.queries:
        parser.error("--query cannot be combined with --golden-cases")

    try:
        queries = (
            load_golden_queries(args.golden_cases)
            if args.golden_cases is not None
            else tuple(
                BenchmarkQuery(query=query) for query in args.queries or DEFAULT_QUERIES
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"invalid --golden-cases file: {exc}")

    return BenchmarkConfig(
        base_url=args.base_url.rstrip("/"),
        queries=queries,
        strategies=tuple(args.strategies or STRATEGIES),
        project=args.project,
        limit=args.limit,
        warmups=args.warmups,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout_seconds,
        token_env=args.token_env,
        output_path=args.output_path,
        golden_cases_path=args.golden_cases,
    )


def _request_headers(token_env: str) -> dict[str, str]:
    token = os.getenv(token_env)
    if token is None or not token.strip():
        return {}
    return {"Authorization": f"Bearer {token.strip()}"}


def _search_payload(
    config: BenchmarkConfig,
    benchmark_query: BenchmarkQuery,
    strategy: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": benchmark_query.query,
        "strategy": strategy,
        "limit": config.limit,
    }
    project = benchmark_query.project or config.project
    if project is not None:
        payload["project"] = project
    return payload


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("response payload must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []


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
    benchmark_query: BenchmarkQuery,
    strategy: str,
) -> SearchObservation:
    started_ns = perf_counter_ns()
    response = await client.post(
        SEARCH_PATH,
        json=_search_payload(config, benchmark_query, strategy),
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
        retrieved_context_ids=retrieved_context_ids(matches),
        retrieved_titles=retrieved_titles(matches),
    )


async def _benchmark_case(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    benchmark_query: BenchmarkQuery,
    strategy: str,
) -> CaseSummary:
    for _ in range(config.warmups):
        try:
            await _observe_search(client, config, benchmark_query, strategy)
        except (httpx.HTTPError, RuntimeError, ValueError):
            break

    observations: list[SearchObservation] = []
    failures: list[str] = []
    for _ in range(config.repetitions):
        try:
            observation = await _observe_search(
                client,
                config,
                benchmark_query,
                strategy,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        else:
            observations.append(observation)
    return summarize_case(benchmark_query, strategy, observations, failures)


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
        cases = tuple(
            [
                await _benchmark_case(client, config, benchmark_query, strategy)
                for benchmark_query in config.queries
                for strategy in config.strategies
            ]
        )

    environment = BenchmarkEnvironment(
        measured_at=datetime.now(UTC).isoformat(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        base_url=config.base_url,
        project=config.project,
        limit=config.limit,
        warmups=config.warmups,
        repetitions=config.repetitions,
        golden_case_count=sum(
            bool(item.expected_context_ids or item.expected_titles)
            for item in config.queries
        ),
        golden_cases_path=(
            None
            if config.golden_cases_path is None
            else str(config.golden_cases_path.resolve())
        ),
        graph_phase_timing_available=False,
        server_memory_timing_available=False,
    )
    return BenchmarkReport(
        environment=environment,
        rag_status=rag_status,
        cases=cases,
        quality_by_strategy=tuple(
            summarize_strategy_quality(strategy, cases)
            for strategy in config.strategies
        ),
    )


def main() -> None:
    """Run the benchmark and emit one machine-readable JSON report."""
    config = _parse_args()
    report = asyncio.run(_run(config))
    rendered = json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(f"{rendered}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
