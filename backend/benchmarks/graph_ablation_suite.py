"""Read-only graph depth 0/1/2 ablation over Memory Evaluation multi-hop truth cases."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter_ns

import httpx
import orjson

from app.memory.domain.event_enum.context_enums import RagStrategy
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphTraversalRequest,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphTraversalDirection,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.domain.repositories.obsidian_graph_traversal_compute_provider import (
    IObsidianGraphTraversalComputeProvider,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_traversal_compute_provider import (
    create_native_obsidian_graph_traversal_compute_provider,
)
from app.obsidian.infrastructure.graph.postgresql_obsidian_graph_projection_repository import (
    PostgreSqlObsidianGraphProjectionRepository,
)
from app.platform.config.database_config import DatabaseConfig
from app.shared.infrastructure.database import Database
from benchmarks.graph_ablation_contracts import (
    GraphAblationCaseObservation,
    GraphAblationReport,
)
from benchmarks.graph_ablation_metrics import (
    build_depth_observation,
    summarize_graph_ablation_depth,
)
from benchmarks.memory_eval_contracts import MemoryEvalCase, MemoryEvalQueryClass
from benchmarks.memory_eval_corpus import load_memory_eval_cases

SEARCH_PATH = "/memory/contexts/retrieval/search"
DEFAULT_TOKEN_ENV = "ALEXANDRIA_BENCHMARK_BEARER_TOKEN"
DEFAULT_CORPUS_PATH = Path(__file__).with_name("memory_eval_cases.v1.json")
_ABLATION_DEPTHS = (0, 1, 2)
_OBSIDIAN_PREFIX = "obsidian:"


@dataclass(frozen=True, slots=True, kw_only=True)
class _GraphAblationConfig:
    """Validated configuration for one graph depth ablation run."""

    base_url: str
    corpus_path: Path
    cases: tuple[MemoryEvalCase, ...]
    strategy: RagStrategy
    search_limit: int
    timeout_seconds: float
    token_env: str
    max_seeds: int
    max_results_per_seed: int
    output_path: Path | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _PrimaryObservation:
    """Primary retrieval seeds for one graph multi-hop truth case."""

    case: MemoryEvalCase
    context_ids: tuple[str, ...]
    search_ms: float


def _parse_args() -> _GraphAblationConfig:
    """Parse and validate graph-ablation CLI configuration.

    Returns:
        Immutable graph-ablation configuration.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Measure expected-target discovery and expansion cost for graph depth 0/1/2 "
            "without changing production retrieval ranking."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument(
        "--strategy",
        choices=tuple(strategy.value for strategy in RagStrategy),
        default=RagStrategy.HYBRID.value,
    )
    parser.add_argument("--search-limit", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--graph-max-seeds", type=int, default=5)
    parser.add_argument("--graph-max-results-per-seed", type=int, default=50)
    parser.add_argument("--output", type=Path, dest="output_path")
    args = parser.parse_args()
    if args.search_limit < 1 or args.search_limit > 50:
        parser.error("--search-limit must be between 1 and 50")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if args.graph_max_seeds < 1 or args.graph_max_seeds > 50:
        parser.error("--graph-max-seeds must be between 1 and 50")
    if args.graph_max_results_per_seed < 1 or args.graph_max_results_per_seed > 500:
        parser.error("--graph-max-results-per-seed must be between 1 and 500")
    try:
        all_cases = load_memory_eval_cases(args.corpus)
    except (OSError, ValueError) as exc:
        parser.error(f"invalid --corpus file: {exc}")
    cases = tuple(
        case
        for case in all_cases
        if case.query_class is MemoryEvalQueryClass.MULTI_HOP_GRAPH
    )
    if not cases:
        parser.error("--corpus contains no MULTI_HOP_GRAPH cases")
    return _GraphAblationConfig(
        base_url=args.base_url.rstrip("/"),
        corpus_path=args.corpus,
        cases=cases,
        strategy=RagStrategy(args.strategy),
        search_limit=args.search_limit,
        timeout_seconds=args.timeout_seconds,
        token_env=args.token_env,
        max_seeds=args.graph_max_seeds,
        max_results_per_seed=args.graph_max_results_per_seed,
        output_path=args.output_path,
    )


def _request_headers(token_env: str) -> dict[str, str]:
    """Build optional bearer headers for local benchmark access.

    Args:
        token_env: Environment variable containing a bearer token.

    Returns:
        Empty or bearer-authenticated request headers.
    """
    token = os.getenv(token_env)
    return (
        {}
        if token is None or not token.strip()
        else {"Authorization": f"Bearer {token.strip()}"}
    )


def _search_payload(
    case: MemoryEvalCase, config: _GraphAblationConfig
) -> dict[str, object]:
    """Build one strict primary retrieval request.

    Args:
        case: Multi-hop truth case.
        config: Graph-ablation configuration.

    Returns:
        Public search request payload.
    """
    payload: dict[str, object] = {
        "query": case.query,
        "strategy": config.strategy.value,
        "limit": config.search_limit,
    }
    if case.project is not None:
        payload["project"] = case.project
    if case.include_scopes:
        payload["include_scopes"] = list(case.include_scopes)
    if case.include_lifecycle_statuses:
        payload["include_lifecycle_statuses"] = list(case.include_lifecycle_statuses)
    return payload


async def _primary_observation(
    client: httpx.AsyncClient,
    case: MemoryEvalCase,
    config: _GraphAblationConfig,
) -> _PrimaryObservation:
    """Execute one primary retrieval and collect graph seed identities.

    Args:
        client: Shared public HTTP client.
        case: Multi-hop truth case.
        config: Graph-ablation configuration.

    Returns:
        Primary graph seed identities and search latency.

    Raises:
        RuntimeError: If the public search request fails.
        ValueError: If the response shape is invalid.
    """
    started_ns = perf_counter_ns()
    response = await client.post(SEARCH_PATH, json=_search_payload(case, config))
    elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
    if response.is_error:
        detail = " ".join(response.text.split())[:240]
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(
            "GRAPH_ABLATION_SEARCH_RESPONSE_INVALID: root must be an object"
        )
    raw_matches = payload.get("matches")
    if not isinstance(raw_matches, list):
        raise ValueError(
            "GRAPH_ABLATION_SEARCH_RESPONSE_INVALID: matches must be a list"
        )
    context_ids = tuple(
        context_id
        for match in raw_matches
        if isinstance(match, dict)
        for context_id in (_public_context_id(match),)
        if context_id is not None
    )
    return _PrimaryObservation(case=case, context_ids=context_ids, search_ms=elapsed_ms)


def _public_context_id(match: dict[object, object]) -> str | None:
    """Extract the canonical Context identity from one public match.

    Args:
        match: Decoded public match payload.

    Returns:
        Canonical Context identity when present.
    """
    canonical = match.get("canonical_context_id")
    if isinstance(canonical, str) and canonical:
        return canonical
    context = match.get("context")
    if not isinstance(context, dict):
        return None
    context_id = context.get("id")
    return context_id if isinstance(context_id, str) and context_id else None


def _graph_note_id(context_id: str) -> str:
    """Normalize one public Context identity to the graph projection note identity.

    Args:
        context_id: Canonical or source-qualified Context identity.

    Returns:
        Active graph projection note identity.
    """
    return context_id.removeprefix(_OBSIDIAN_PREFIX)


def _traversal_requests(
    primary: _PrimaryObservation,
    depth: int,
    max_seeds: int,
    max_results_per_seed: int,
) -> tuple[ObsidianGraphTraversalRequest, ...]:
    """Build bounded graph traversal requests from primary retrieval seeds.

    Args:
        primary: Primary retrieval observation.
        depth: Requested graph depth.
        max_seeds: Maximum number of ranked primary results used as graph seeds.
        max_results_per_seed: Maximum returned nodes per seed.

    Returns:
        Stable deduplicated traversal requests.
    """
    relations = tuple(primary.case.required_graph_relations)
    seeds = tuple(
        dict.fromkeys(_graph_note_id(value) for value in primary.context_ids)
    )[:max_seeds]
    return tuple(
        ObsidianGraphTraversalRequest(
            request_id=f"{primary.case.case_id}:d{depth}:s{index}",
            start_note_id=seed,
            direction=ObsidianGraphTraversalDirection.BOTH,
            relations=relations,
            max_depth=depth,
            max_results=max_results_per_seed,
        )
        for index, seed in enumerate(seeds)
    )


def _depth_observation(
    primary: _PrimaryObservation,
    projection: ObsidianGraphProjection,
    provider: IObsidianGraphTraversalComputeProvider,
    depth: int,
    max_seeds: int,
    max_results_per_seed: int,
):
    """Execute one graph depth and build a truth-aware observation.

    Args:
        primary: Primary retrieval seeds.
        projection: Active graph projection snapshot.
        provider: Deterministic graph traversal compute provider.
        depth: Graph traversal depth.
        max_seeds: Maximum number of ranked primary results used as graph seeds.
        max_results_per_seed: Per-seed traversal bound.

    Returns:
        Graph depth observation for the case.
    """
    primary_ids = tuple(_graph_note_id(value) for value in primary.context_ids)
    expected_ids = tuple(
        _graph_note_id(value) for value in primary.case.expected_context_ids
    )
    if depth == 0 or not primary_ids:
        return build_depth_observation(
            depth=depth,
            primary_ids=primary_ids,
            expected_ids=expected_ids,
            discovered_ids=primary_ids,
            minimum_expected_matches=primary.case.minimum_expected_matches,
            traversal_request_count=0,
            traversal_truncated_count=0,
            graph_compute_ms=0.0,
        )
    requests = _traversal_requests(primary, depth, max_seeds, max_results_per_seed)
    started_ns = perf_counter_ns()
    results = provider.traverse(projection, requests)
    graph_compute_ms = (perf_counter_ns() - started_ns) / 1_000_000
    discovered = list(primary_ids)
    truncated = 0
    for result in results:
        discovered.extend(visit.note_id for visit in result.visits)
        truncated += int(result.truncated)
    return build_depth_observation(
        depth=depth,
        primary_ids=primary_ids,
        expected_ids=expected_ids,
        discovered_ids=tuple(dict.fromkeys(discovered)),
        minimum_expected_matches=primary.case.minimum_expected_matches,
        traversal_request_count=len(requests),
        traversal_truncated_count=truncated,
        graph_compute_ms=graph_compute_ms,
    )


async def _run(config: _GraphAblationConfig) -> GraphAblationReport:
    """Run primary retrieval plus graph depth 0/1/2 candidate-discovery ablation.

    Args:
        config: Validated graph-ablation configuration.

    Returns:
        Reproducible graph candidate-discovery report.

    Raises:
        RuntimeError: If the graph read model is disabled.
    """
    timeout = httpx.Timeout(config.timeout_seconds)
    async with httpx.AsyncClient(
        base_url=config.base_url,
        timeout=timeout,
        headers=_request_headers(config.token_env),
    ) as client:
        primary = tuple(
            [await _primary_observation(client, case, config) for case in config.cases]
        )
    database = Database(DatabaseConfig().url)
    await database.initialize()
    try:
        repository = PostgreSqlObsidianGraphProjectionRepository(
            database=database,
            compute_provider=create_native_obsidian_graph_projection_compute_provider(),
        )
        projection, snapshot_ms = await _projection_snapshot(repository)
    finally:
        await database.shutdown()
    provider = create_native_obsidian_graph_traversal_compute_provider()
    cases = tuple(
        GraphAblationCaseObservation(
            case_id=item.case.case_id,
            query=item.case.query,
            primary_context_ids=tuple(
                _graph_note_id(value) for value in item.context_ids
            ),
            expected_context_ids=tuple(
                _graph_note_id(value) for value in item.case.expected_context_ids
            ),
            search_ms=item.search_ms,
            depths=tuple(
                _depth_observation(
                    item,
                    projection,
                    provider,
                    depth,
                    config.max_seeds,
                    config.max_results_per_seed,
                )
                for depth in _ABLATION_DEPTHS
            ),
        )
        for item in primary
    )
    return GraphAblationReport(
        schema_version=1,
        graph_compute_authority=provider.authority,
        strategy=config.strategy.value,
        search_limit=config.search_limit,
        graph_max_seeds=config.max_seeds,
        graph_max_results_per_seed=config.max_results_per_seed,
        projection_node_count=len(projection.nodes),
        projection_edge_count=len(projection.edges),
        projection_snapshot_ms=snapshot_ms,
        cases=cases,
        summaries=tuple(
            summarize_graph_ablation_depth(cases, depth) for depth in _ABLATION_DEPTHS
        ),
    )


async def _projection_snapshot(
    repository: IObsidianGraphProjectionRepository,
) -> tuple[ObsidianGraphProjection, float]:
    """Read the active graph projection and measure Python effect-boundary latency.

    Args:
        repository: Enabled graph projection repository.

    Returns:
        Active projection and snapshot fetch latency in milliseconds.
    """
    started_ns = perf_counter_ns()
    projection = await repository.snapshot()
    return projection, (perf_counter_ns() - started_ns) / 1_000_000


def main() -> None:
    """Run graph ablation and emit deterministic JSON evidence."""
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
