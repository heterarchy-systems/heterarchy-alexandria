"""Read-only end-to-end runner for the Alexandria Memory Evaluation Suite."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import httpx
import orjson

from app.memory.domain.event_enum.context_enums import RagStrategy
from benchmarks.memory_eval_contracts import (
    MemoryEvalCase,
    MemoryEvalEnvironment,
    MemoryEvalObservation,
    MemoryEvalQueryClass,
    MemoryEvalReport,
)
from benchmarks.memory_eval_corpus import load_memory_eval_cases
from benchmarks.memory_eval_metrics import (
    summarize_memory_eval_case,
    summarize_memory_eval_strategy,
)

SEARCH_PATH = "/memory/contexts/retrieval/search"
RAG_STATUS_PATH = "/memory/contexts/rag/status"
READINESS_PATH = "/operations/readiness"
RETRIEVAL_KERNEL_AUTHORITY_HEADER = "X-Alexandria-Retrieval-Kernel-Authority"
DEFAULT_TOKEN_ENV = "ALEXANDRIA_BENCHMARK_BEARER_TOKEN"
DEFAULT_CORPUS_PATH = Path(__file__).with_name("memory_eval_cases.v1.json")
STRATEGY_CHOICES = tuple(strategy.value for strategy in RagStrategy)
DEFAULT_STRATEGIES = tuple(strategy.value for strategy in RagStrategy.fixed())


@dataclass(frozen=True, slots=True, kw_only=True)
class _MemoryEvalConfig:
    """Validated command-line configuration for one memory-evaluation run."""

    base_url: str
    corpus_path: Path
    cases: tuple[MemoryEvalCase, ...]
    strategies: tuple[str, ...]
    limit: int
    repetitions: int
    timeout_seconds: float
    token_env: str
    output_path: Path | None


def _parse_args() -> _MemoryEvalConfig:
    """Parse and validate the Memory Evaluation Suite CLI.

    Returns:
        Immutable validated runner configuration.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate Alexandria durable-memory retrieval with a versioned read-only "
            "truth corpus."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument(
        "--strategy",
        action="append",
        choices=STRATEGY_CHOICES,
        dest="strategies",
    )
    parser.add_argument(
        "--query-class",
        action="append",
        choices=tuple(query_class.value for query_class in MemoryEvalQueryClass),
        dest="query_classes",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--output", type=Path, dest="output_path")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 50:
        parser.error("--limit must be between 1 and 50")
    if args.repetitions < 1:
        parser.error("--repetitions must be one or greater")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    try:
        cases = load_memory_eval_cases(args.corpus)
    except (OSError, ValueError) as exc:
        parser.error(f"invalid --corpus file: {exc}")
    if args.query_classes:
        selected_classes = {MemoryEvalQueryClass(value) for value in args.query_classes}
        cases = tuple(case for case in cases if case.query_class in selected_classes)
        if not cases:
            parser.error("--query-class filter selected no corpus cases")
    return _MemoryEvalConfig(
        base_url=args.base_url.rstrip("/"),
        corpus_path=args.corpus,
        cases=cases,
        strategies=tuple(args.strategies or DEFAULT_STRATEGIES),
        limit=args.limit,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout_seconds,
        token_env=args.token_env,
        output_path=args.output_path,
    )


def _request_headers(token_env: str) -> dict[str, str]:
    """Build optional bearer authentication headers for local benchmark access.

    Args:
        token_env: Environment variable containing the optional bearer token.

    Returns:
        Empty or bearer-authenticated HTTP header mapping.
    """
    token = os.getenv(token_env)
    if token is None or not token.strip():
        return {}
    return {"Authorization": f"Bearer {token.strip()}"}


def _search_payload(
    case: MemoryEvalCase,
    strategy: str,
    limit: int,
) -> dict[str, object]:
    """Build one strict public search request from explicit benchmark truth.

    Args:
        case: Memory-evaluation truth case.
        strategy: Requested retrieval strategy.
        limit: Maximum result count.

    Returns:
        JSON-compatible search request payload.
    """
    payload: dict[str, object] = {
        "query": case.query,
        "strategy": strategy,
        "limit": limit,
    }
    if case.project is not None:
        payload["project"] = case.project
    if case.include_scopes:
        payload["include_scopes"] = list(case.include_scopes)
    if case.include_lifecycle_statuses:
        payload["include_lifecycle_statuses"] = list(case.include_lifecycle_statuses)
    return payload


def _mapping(value: object) -> dict[str, object]:
    """Narrow one decoded JSON object for benchmark parsing.

    Args:
        value: Decoded JSON value.

    Returns:
        String-keyed object mapping.

    Raises:
        ValueError: If the value is not an object.
    """
    if not isinstance(value, dict):
        raise ValueError("response payload must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[object]:
    """Return one decoded list without coercing other JSON shapes.

    Args:
        value: Decoded JSON value.

    Returns:
        Original list or an empty list for non-list values.
    """
    return value if isinstance(value, list) else []


def _optional_string(value: object) -> str | None:
    """Return a string value only when the decoded JSON type is exact.

    Args:
        value: Decoded JSON value.

    Returns:
        String value or None.
    """
    return value if isinstance(value, str) else None


def _match_context_id(raw_match: dict[str, object]) -> str:
    """Return the best public Context identity for one match.

    Args:
        raw_match: Decoded search match object.

    Returns:
        Canonical Context id or an empty placeholder.
    """
    canonical = raw_match.get("canonical_context_id")
    if isinstance(canonical, str):
        return canonical
    context = raw_match.get("context")
    if not isinstance(context, dict):
        return ""
    context_id = context.get("id")
    return context_id if isinstance(context_id, str) else ""


def _match_title(raw_match: dict[str, object]) -> str:
    """Return one public Context title without exposing content.

    Args:
        raw_match: Decoded search match object.

    Returns:
        Context title or an empty placeholder.
    """
    context = raw_match.get("context")
    if not isinstance(context, dict):
        return ""
    title = context.get("title")
    return title if isinstance(title, str) else ""


def _match_lifecycle(raw_match: dict[str, object]) -> str | None:
    """Return the public recall lifecycle state for one match.

    Args:
        raw_match: Decoded search match object.

    Returns:
        Lifecycle value or None.
    """
    return _optional_string(raw_match.get("lifecycle_status"))


def _graph_evidence_summary(matches: list[object]) -> tuple[tuple[str, ...], int]:
    """Collect relation names and maximum distance from public graph evidence.

    Args:
        matches: Decoded public search match list.

    Returns:
        Deduplicated relation names and maximum observed graph distance.
    """
    relations: list[str] = []
    max_distance = 0
    for raw_match in matches:
        if not isinstance(raw_match, dict):
            continue
        for raw_evidence in _sequence(raw_match.get("graph_evidence")):
            if not isinstance(raw_evidence, dict):
                continue
            relation = raw_evidence.get("relation")
            if isinstance(relation, str) and relation:
                relations.append(relation)
            distance = raw_evidence.get("distance")
            if isinstance(distance, int) and not isinstance(distance, bool):
                max_distance = max(max_distance, distance)
    return tuple(dict.fromkeys(relations)), max_distance


async def observe_memory_search(
    client: httpx.AsyncClient,
    case: MemoryEvalCase,
    strategy: str,
    limit: int,
) -> MemoryEvalObservation:
    """Execute one public read-only search observation.

    Args:
        client: Shared HTTP benchmark client.
        case: Explicit memory-evaluation truth.
        strategy: Requested retrieval strategy.
        limit: Maximum returned matches.

    Returns:
        Bounded public observation used by pure metrics.

    Raises:
        RuntimeError: If the public endpoint returns an error status.
        ValueError: If the response body is not the expected JSON shape.
    """
    started_ns = perf_counter_ns()
    response = await client.post(
        SEARCH_PATH,
        json=_search_payload(case, strategy, limit),
    )
    elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
    if response.is_error:
        detail = " ".join(response.text.split())[:240]
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    payload = _mapping(response.json())
    raw_matches = _sequence(payload.get("matches"))
    matches = [item for item in raw_matches if isinstance(item, dict)]
    warnings = _sequence(payload.get("warnings"))
    graph_relations, graph_max_distance = _graph_evidence_summary(raw_matches)
    return MemoryEvalObservation(
        elapsed_ms=elapsed_ms,
        effective_strategy=_optional_string(payload.get("effective_strategy")),
        retrieved_context_ids=tuple(_match_context_id(item) for item in matches),
        retrieved_titles=tuple(_match_title(item) for item in matches),
        retrieved_lifecycle_statuses=tuple(_match_lifecycle(item) for item in matches),
        graph_relations=graph_relations,
        graph_max_distance=graph_max_distance,
        warning_count=len(warnings),
        response_bytes=len(response.content),
    )


async def _read_runtime_evidence(
    client: httpx.AsyncClient,
) -> tuple[str | None, object]:
    """Read retrieval authority and runtime provenance without mutating state.

    Args:
        client: Shared HTTP benchmark client.

    Returns:
        Retrieval-kernel authority and runtime provenance payload.
    """
    rag_response = await client.get(RAG_STATUS_PATH)
    authority = (
        None
        if rag_response.is_error
        else rag_response.headers.get(RETRIEVAL_KERNEL_AUTHORITY_HEADER)
    )
    readiness_response = await client.get(READINESS_PATH)
    if readiness_response.is_error:
        detail = " ".join(readiness_response.text.split())[:240]
        return authority, {
            "status_code": readiness_response.status_code,
            "error": detail,
        }
    readiness = _mapping(readiness_response.json())
    return authority, readiness.get("runtime")


async def _run(config: _MemoryEvalConfig) -> MemoryEvalReport:
    """Run selected read-only cases and return one evidence-bearing report.

    Args:
        config: Validated runner configuration.

    Returns:
        Full Memory Evaluation Suite report.
    """
    timeout = httpx.Timeout(config.timeout_seconds)
    async with httpx.AsyncClient(
        base_url=config.base_url,
        timeout=timeout,
        headers=_request_headers(config.token_env),
    ) as client:
        authority, runtime_provenance = await _read_runtime_evidence(client)
        case_metrics = []
        for case in config.cases:
            for strategy in config.strategies:
                observations: list[MemoryEvalObservation] = []
                failures: list[str] = []
                for _ in range(config.repetitions):
                    try:
                        observations.append(
                            await observe_memory_search(
                                client,
                                case,
                                strategy,
                                config.limit,
                            )
                        )
                    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                        failures.append(f"{type(exc).__name__}: {exc}")
                case_metrics.append(
                    summarize_memory_eval_case(
                        case,
                        strategy,
                        observations,
                        failures,
                    )
                )
    corpus_bytes = config.corpus_path.read_bytes()
    cases = tuple(case_metrics)
    environment = MemoryEvalEnvironment(
        measured_at=datetime.now(UTC).isoformat(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        base_url=config.base_url,
        corpus_path=str(config.corpus_path.resolve()),
        corpus_sha256=hashlib.sha256(corpus_bytes).hexdigest(),
        corpus_case_count=len(config.cases),
        strategies=config.strategies,
        limit=config.limit,
        repetitions=config.repetitions,
        retrieval_kernel_authority=authority,
        runtime_provenance=runtime_provenance,
    )
    return MemoryEvalReport(
        environment=environment,
        cases=cases,
        quality_by_strategy=tuple(
            summarize_memory_eval_strategy(strategy, cases)
            for strategy in config.strategies
        ),
    )


def main() -> None:
    """Run the Memory Evaluation Suite and emit deterministic JSON evidence."""
    config = _parse_args()
    report = asyncio.run(_run(config))
    rendered = orjson.dumps(
        asdict(report),
        option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
    )
    sys.stdout.buffer.write(rendered + b"\n")
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_bytes(rendered + b"\n")


if __name__ == "__main__":
    main()
