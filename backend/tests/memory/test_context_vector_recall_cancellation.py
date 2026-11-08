from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from typing import cast

import anyio
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)

from app.memory.application.contexts.embedding.context_vector_recall_service import (
    ContextVectorRecallService,
)
from app.memory.application.retrieval.embeddings.fake_embedding_provider import (
    FakeEmbeddingProvider,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextRecallFilter,
    ContextVectorRecall,
    ScopeIdentity,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)


class _BlockingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__(dimensions=2)
        self.started = threading.Event()
        self.release = threading.Event()

    def embed_query(self, text: str) -> list[float]:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("Test did not release the blocked embedding")
        return [0.25, 0.75]


class _RecordingVectorSource:
    def __init__(self) -> None:
        self.calls = 0

    async def search_vector(
        self, recall: ContextVectorRecall
    ) -> list[ContextSearchMatch]:
        self.calls += 1
        return []


def test_cancelled_vector_recall_waits_for_query_embedding_before_propagating() -> None:
    provider = _BlockingEmbeddingProvider()
    source = _RecordingVectorSource()
    service = ContextVectorRecallService(
        provider=provider,
        search_sources=[cast(IContextSearchSource, source)],
        retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
    )
    recall_filter = ContextRecallFilter(
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
    )

    async def scenario() -> None:
        search_task = asyncio.create_task(service.search("query", recall_filter))
        try:
            assert await asyncio.to_thread(provider.started.wait, timeout=3)
            search_task.cancel()
            cancellation_processed = asyncio.Event()
            asyncio.get_running_loop().call_soon(cancellation_processed.set)
            await cancellation_processed.wait()
            assert not search_task.done()
        finally:
            provider.release.set()
            with suppress(asyncio.CancelledError):
                await search_task

        assert search_task.cancelled()
        assert source.calls == 0

    anyio.run(scenario)
