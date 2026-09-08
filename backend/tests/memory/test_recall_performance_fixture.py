"""Measured Recall routing evidence over the real PostgreSQL/native fixture."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from typing import cast

import anyio
from sqlalchemy import event
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)
from tests.memory.context_seed import seed_context
from tests.memory.test_context_repository import KeywordEmbeddingProvider

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.recall_service import RecallService
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.context_read_models import (
    ContextPack,
    ContextSearchMatch,
)
from app.memory.domain.entities.recall import RecallResult
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    RagStrategy,
)
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.memory.interface.schemas.context.context_mapping import pack_payload
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextPackResponse,
)
from app.memory.interface.schemas.context.recall_schema import RecallResponseSchema
from app.shared.infrastructure.database import Database

_SAMPLES = 20
_OUTPUT_PATH = Path(
    os.environ.get(
        "ALEXANDRIA_RECALL_PERF_OUTPUT",
        "/tmp/alexandria-recall-after-fixture.json",
    )
)


class _ExactEmpty:
    """Typed no-op exact resolver for the performance fixture."""

    async def resolve(
        self,
        selector: object,
        scope_identity: ScopeIdentity,
    ) -> tuple[ContextSearchMatch, ...]:
        del selector, scope_identity
        return ()


class _CountingKeywordEmbeddingProvider(KeywordEmbeddingProvider):
    """Deterministic fixture provider with explicit query-call evidence."""

    def __init__(self) -> None:
        self.query_calls = 0
        self.document_calls = 0

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return super().embed_query(text)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        return super().embed_documents(texts)


@dataclass(slots=True)
class _Counters:
    sql_statements: int = 0
    temporal_batch_queries: int = 0
    fts_queries: int = 0
    vector_queries: int = 0

    def reset(self) -> None:
        self.sql_statements = 0
        self.temporal_batch_queries = 0
        self.fts_queries = 0
        self.vector_queries = 0


@asynccontextmanager
async def _database() -> AsyncIterator[Database]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        yield database
    finally:
        await database.shutdown()


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _context_ids(value: object) -> list[str]:
    if isinstance(value, ContextPack):
        return [match.context.id for match in value.matches]
    result = cast(RecallResult, value)
    return [item.match.context.id for item in result.matches]


def _outcome(value: object) -> str:
    if isinstance(value, ContextPack):
        return "CONTEXT_PACK"
    return cast(RecallResult, value).outcome.value


def _routes(value: object) -> list[str]:
    if isinstance(value, ContextPack):
        return [value.effective_strategy.value]
    result = cast(RecallResult, value)
    return [stage.route.value for stage in result.trace.stages]


async def _measure(
    operation: Callable[[], Awaitable[object]],
    serialize: Callable[[object], str],
    counters: _Counters,
    provider: _CountingKeywordEmbeddingProvider,
) -> dict[str, object]:
    """Measure routing, SQL, embedding, and bounded JSON serialization."""
    for _ in range(2):
        result = await operation()
        serialize(result)
    counters.reset()
    provider.query_calls = 0
    provider.document_calls = 0
    operation_times: list[float] = []
    serialization_times: list[float] = []
    payload_sizes: list[int] = []
    outcomes: list[str] = []
    first_ids: list[str] = []
    first_routes: list[str] = []
    for _ in range(_SAMPLES):
        started = perf_counter_ns()
        result = await operation()
        operation_times.append((perf_counter_ns() - started) / 1_000_000)
        started = perf_counter_ns()
        payload = serialize(result)
        serialization_times.append((perf_counter_ns() - started) / 1_000_000)
        payload_sizes.append(len(payload.encode()))
        outcomes.append(_outcome(result))
        first_ids = _context_ids(result)
        first_routes = _routes(result)
    return {
        "samples": _SAMPLES,
        "operation_ms": {
            "p50": median(operation_times),
            "p95": _percentile(operation_times, 0.95),
        },
        "serialization_ms": {
            "p50": median(serialization_times),
            "p95": _percentile(serialization_times, 0.95),
        },
        "payload_bytes": {
            "median": median(payload_sizes),
            "max": max(payload_sizes),
        },
        "sql_statements": counters.sql_statements,
        "temporal_batch_queries": counters.temporal_batch_queries,
        "fts_queries": counters.fts_queries,
        "vector_queries": counters.vector_queries,
        "embedding_query_calls": provider.query_calls,
        "embedding_document_calls": provider.document_calls,
        "outcomes": sorted(set(outcomes)),
        "sample_context_ids": first_ids,
        "sample_routes": first_routes,
    }


def test_real_postgres_recall_performance_fixture() -> None:
    """Capture routing overhead without making a real model-quality claim."""

    async def scenario() -> dict[str, object]:
        provider = _CountingKeywordEmbeddingProvider()
        async with _database() as database, database.session() as session:
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=provider,
                vector_retrieval_enabled=True,
            )
            await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Current architecture decision",
                summary="Lexical primary target.",
                content="# Current architecture\n\nLexical decision evidence.",
                project="alexandria",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Semantic target",
                summary="Vector primary target.",
                content="# Semantic target\n\nsemantic-target evidence.",
                project="alexandria",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Forge related target",
                summary="Vector related target.",
                content="# Forge target\n\nsemantic-target evidence.",
                project="forge",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            await session.commit()
            temporal_service = MemoryTemporalRecallService(
                context_service=context_service,
                repository=SqlAlchemyMemoryReconciliationRepository(session),
            )
            recall_service = RecallService(
                context_service=context_service,
                temporal_recall_service=temporal_service,
                exact_selector_resolver=_ExactEmpty(),
            )
            counters = _Counters()

            def count_sql(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                counters.sql_statements += 1
                lowered = statement.casefold()
                if "context_temporal_states" in lowered:
                    counters.temporal_batch_queries += 1
                if "ts_rank" in lowered or "@@" in lowered:
                    counters.fts_queries += 1
                if "<=>" in lowered:
                    counters.vector_queries += 1

            event.listen(
                database.engine.sync_engine, "before_cursor_execute", count_sql
            )
            try:
                baseline_operations: dict[str, Callable[[], Awaitable[object]]] = {
                    "primary_match": lambda: context_service.search(
                        query="Current architecture decision",
                        strategy=RagStrategy.FTS_ONLY,
                        limit=3,
                        project="alexandria",
                        include_scopes=[ContextScope.PROJECT, ContextScope.GLOBAL],
                    ),
                    "semantic_paraphrase": lambda: context_service.search(
                        query="query-alias",
                        strategy=RagStrategy.HYBRID,
                        limit=3,
                        project="alexandria",
                        include_scopes=[ContextScope.PROJECT, ContextScope.GLOBAL],
                    ),
                    "related_project": lambda: context_service.search(
                        query="query-alias",
                        strategy=RagStrategy.HYBRID,
                        limit=3,
                        project="forge",
                        include_scopes=[ContextScope.PROJECT, ContextScope.GLOBAL],
                    ),
                    "related_global_exhaustion": lambda: context_service.search(
                        query="no-such-memory-token",
                        strategy=RagStrategy.HYBRID,
                        limit=3,
                        project="missing-primary",
                        include_scopes=[ContextScope.PROJECT, ContextScope.GLOBAL],
                    ),
                }
                high_level_operations: dict[str, Callable[[], Awaitable[object]]] = {
                    "primary_match": lambda: recall_service.recall(
                        RecallRequest(
                            query="Current architecture decision",
                            project="alexandria",
                        )
                    ),
                    "semantic_paraphrase": lambda: recall_service.recall(
                        RecallRequest(query="query-alias", project="alexandria")
                    ),
                    "related_project": lambda: recall_service.recall(
                        RecallRequest(
                            query="query-alias",
                            project="missing-primary",
                            related_projects=("forge",),
                        )
                    ),
                    "related_global_exhaustion": lambda: recall_service.recall(
                        RecallRequest(
                            query="no-such-memory-token",
                            project="missing-primary",
                        )
                    ),
                }

                def serialize_baseline(value: object) -> str:
                    response = ContextPackResponse.model_validate(
                        pack_payload(cast(ContextPack, value))
                    )
                    return response.model_dump_json()

                def serialize_high_level(value: object) -> str:
                    return RecallResponseSchema.from_entity(
                        cast(RecallResult, value)
                    ).model_dump_json()

                measurements: dict[str, object] = {}
                for name, operation in baseline_operations.items():
                    measurements.setdefault(name, {})
                    cast(dict[str, object], measurements[name])[
                        "baseline_context_service"
                    ] = await _measure(
                        operation, serialize_baseline, counters, provider
                    )
                for name, operation in high_level_operations.items():
                    cast(dict[str, object], measurements[name])[
                        "high_level_recall"
                    ] = await _measure(
                        operation, serialize_high_level, counters, provider
                    )
            finally:
                event.remove(
                    database.engine.sync_engine, "before_cursor_execute", count_sql
                )

        for value in measurements.values():
            item = cast(dict[str, object], value)
            baseline = cast(dict[str, object], item["baseline_context_service"])
            high_level = cast(dict[str, object], item["high_level_recall"])
            item["delta"] = {
                "sql_statements": cast(int, high_level["sql_statements"])
                - cast(int, baseline["sql_statements"]),
                "temporal_batch_queries": cast(
                    int, high_level["temporal_batch_queries"]
                )
                - cast(int, baseline["temporal_batch_queries"]),
                "fts_queries": cast(int, high_level["fts_queries"])
                - cast(int, baseline["fts_queries"]),
                "vector_queries": cast(int, high_level["vector_queries"])
                - cast(int, baseline["vector_queries"]),
                "embedding_query_calls": cast(int, high_level["embedding_query_calls"])
                - cast(int, baseline["embedding_query_calls"]),
            }
        return cast(dict[str, object], measurements)

    measurements = anyio.run(scenario)
    payload = {
        "fixture": {
            "database": "temporary PostgreSQL pgvector",
            "embedding": "deterministic KeywordEmbeddingProvider",
            "native": "TestContextRetrievalKernelProvider with native library loaded",
            "samples": _SAMPLES,
            "claim_boundary": "routing overhead only; no real-model quality claim",
        },
        "operations": measurements,
    }
    _OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    assert _OUTPUT_PATH.exists()
