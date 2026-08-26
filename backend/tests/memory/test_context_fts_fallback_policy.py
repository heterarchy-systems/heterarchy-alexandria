"""Lexical query fallback execution policy tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import anyio
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)

from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.contexts.records.context_search_service import (
    ContextSearchService,
)
from app.memory.application.retrieval.context_retrieval_lane_executor import (
    ContextRetrievalLaneExecutor,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextRecallFilter,
    ScopeIdentity,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)


@dataclass(frozen=True, slots=True)
class _FakeContext:
    id: str


@dataclass(frozen=True, slots=True)
class _FakeMatch:
    context: _FakeContext
    score: float


class _RecordingFtsSource:
    def __init__(self, responses: dict[str, list[ContextSearchMatch]]) -> None:
        self.queries: list[str] = []
        self._responses = responses

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        self.queries.append(recall.query)
        return self._responses.get(recall.query, [])


class _FailingEmbeddingService:
    async def recall_health(self) -> None:
        raise AssertionError("FTS_ONLY must not probe vector dependency health")


def _match(context_id: str, score: float = 1.0) -> ContextSearchMatch:
    return cast(
        ContextSearchMatch,
        _FakeMatch(context=_FakeContext(id=context_id), score=score),
    )


def _recall(query: str) -> ContextFtsRecall:
    return ContextFtsRecall(
        query=query,
        recall_filter=ContextRecallFilter(
            limit=5,
            kind=None,
            scope_identity=ScopeIdentity(
                include_scopes=(ContextScope.GLOBAL,),
                project=None,
                workspace_id=None,
                agent_id=None,
                user_id=None,
                session_id=None,
            ),
            lifecycle_statuses=None,
        ),
    )


def _service(source: _RecordingFtsSource) -> ContextSearchService:
    return ContextSearchService(
        search_sources=[cast(IContextSearchSource, source)],
        embedding_service=cast(ContextEmbeddingService, object()),
        retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
    )


def _lane_executor(source: _RecordingFtsSource) -> ContextRetrievalLaneExecutor:
    return ContextRetrievalLaneExecutor(
        search_sources=[cast(IContextSearchSource, source)],
        embedding_service=cast(ContextEmbeddingService, object()),
        retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
    )


def test_fts_only_search_skips_vector_health_probe() -> None:
    """Lexical-only recall should not pay for vector fingerprint health checks."""
    source = _RecordingFtsSource({})
    service = ContextSearchService(
        search_sources=[cast(IContextSearchSource, source)],
        embedding_service=cast(ContextEmbeddingService, _FailingEmbeddingService()),
        retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
    )

    async def scenario():
        return await service.search(
            query="exact lexical query",
            strategy=RagStrategy.FTS_ONLY,
            limit=5,
        )

    pack = anyio.run(scenario)

    assert pack.matches == ()


def test_fts_original_match_stops_before_broader_fallbacks() -> None:
    """A non-empty original lexical query should not execute broader variants."""
    query = "검색 품질 개선을 위해서 뭐가 있을까요?"
    source = _RecordingFtsSource({query: [_match("original")]})

    matches = anyio.run(
        _lane_executor(source).retrieve,
        query,
        RagStrategy.FTS_ONLY,
        5,
        _recall(query).recall_filter,
        None,
        None,
    )

    assert [match.context.id for match in matches] == ["original"]
    assert source.queries == [query]


def test_fts_empty_original_uses_first_nonempty_focused_fallback() -> None:
    """Focused lexical variants should remain fallback lanes when the original is empty."""
    query = "검색 품질 개선을 위해서 뭐가 있을까요?"
    focused = "검색 품질"
    source = _RecordingFtsSource({focused: [_match("focused")]})

    matches = anyio.run(
        _lane_executor(source).retrieve,
        query,
        RagStrategy.FTS_ONLY,
        5,
        _recall(query).recall_filter,
        None,
        None,
    )

    assert [match.context.id for match in matches] == ["focused"]
    assert source.queries == [query, "검색 품질 개선을", focused]
