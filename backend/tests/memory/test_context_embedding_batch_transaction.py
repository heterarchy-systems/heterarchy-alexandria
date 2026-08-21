"""Embedding batch transaction and ordering contracts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

import anyio
from app.memory.application.contexts.embedding.context_embedding_health_service import (
    ContextEmbeddingHealthService,
)
from app.memory.application.contexts.embedding.context_embedding_reindex_service import (
    ContextEmbeddingReindexService,
)
from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.domain.contracts.context_contracts import (
    ContextChunkEmbeddingUpdate,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.infrastructure.context_embedding_batch_transaction import (
    SqlAlchemyContextEmbeddingBatchTransaction,
)
from app.shared.types.extra_types import JSONObject
from sqlalchemy.ext.asyncio import AsyncSession


class _RecordingProvider(EmbeddingProvider):
    def __init__(self, events: list[str]) -> None:
        self._events = events

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def model_name(self) -> str:
        return "test-model"

    @property
    def dimensions(self) -> int:
        return 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self._events.append(f"embed:{len(texts)}")
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class _RecordingSource(IContextSearchSource):
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._normal_chunk = _chunk("normal")
        self._forced_chunk = _chunk("forced")

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        return []

    async def search_vector(
        self,
        recall: ContextVectorRecall,
    ) -> list[ContextSearchMatch]:
        return []

    async def chunks_missing_embeddings(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        limit: int,
        force: bool = False,
    ) -> list[ContextChunkRecord]:
        self._events.append(f"select:{force}")
        if force:
            return [self._normal_chunk, self._forced_chunk][:limit]
        return [self._normal_chunk][:limit]

    async def embedding_index_status(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
    ) -> RagHealthState:
        return RagHealthState.REINDEX_REQUIRED

    async def embedding_source_status(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        raise AssertionError("source status is not used by the reindex ordering test")

    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        self._events.append(f"update:{len(updates)}")
        return len(updates)


class _RecordingBatchTransaction:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def release_read_transaction(self) -> None:
        self._events.append("release")

    async def commit_embedding_updates(self) -> None:
        self._events.append("commit")


class _RecordingSession:
    def __init__(self) -> None:
        self.active = True
        self.events: list[str] = []

    def in_transaction(self) -> bool:
        return self.active

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.active = False

    async def commit(self) -> None:
        self.events.append("commit")
        self.active = False


def test_reindex_commits_each_source_batch_before_next_inference() -> None:
    """Each durable update commits before later CPU work can idle its transaction."""

    async def scenario() -> tuple[list[str], int, int]:
        events: list[str] = []
        provider = _RecordingProvider(events)
        source = _RecordingSource(events)
        health_service = ContextEmbeddingHealthService(
            provider=provider,
            vector_retrieval_enabled=True,
            search_sources=[source],
        )
        service = ContextEmbeddingReindexService(
            provider=provider,
            search_sources=[source],
            health_service=health_service,
            batch_transaction=_RecordingBatchTransaction(events),
        )

        result = await service.reindex(limit=2, force=True)
        return events, result.scanned, result.updated

    events, scanned, updated = anyio.run(scenario)

    assert events == [
        "select:False",
        "select:True",
        "release",
        "embed:1",
        "update:1",
        "commit",
        "embed:1",
        "update:1",
        "commit",
    ]
    assert scanned == 2
    assert updated == 2


def test_sqlalchemy_batch_transaction_releases_reads_and_commits_updates() -> None:
    """The SQLAlchemy adapter owns both sides of the resumable batch boundary."""

    async def scenario() -> list[str]:
        session = _RecordingSession()
        transaction = SqlAlchemyContextEmbeddingBatchTransaction(
            session=cast(AsyncSession, session)
        )

        await transaction.release_read_transaction()
        session.active = True
        await transaction.commit_embedding_updates()
        return session.events

    assert anyio.run(scenario) == ["rollback", "commit"]


def _chunk(chunk_id: str) -> ContextChunkRecord:
    metadata = ContextMetadataPayload(title=f"Title {chunk_id}")
    return ContextChunkRecord(
        id=chunk_id,
        context_id="context-1",
        chunk_index=0,
        heading=None,
        content=f"content {chunk_id}",
        token_count=2,
        content_hash=f"hash-{chunk_id}",
        chunk_metadata=metadata,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
