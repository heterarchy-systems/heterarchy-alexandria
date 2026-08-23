"""Focused contracts for embedding health hot-path and diagnostic probes."""

from __future__ import annotations

import anyio
import pytest
from app.memory.application.contexts.embedding import (
    context_embedding_health_service as health_module,
)
from app.memory.application.contexts.embedding.context_embedding_health_service import (
    ContextEmbeddingHealthService,
)
from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.application.retrieval.embeddings.fake_embedding_provider import (
    FakeEmbeddingProvider,
)
from app.memory.domain.entities.context_read_models import ContextEmbeddingSourceStatus
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)


def _provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(
        model_name="intfloat/multilingual-e5-small",
        dimensions=384,
    )


def test_recall_health_skips_expensive_source_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search requests should probe mismatch status without counting all source rows."""
    calls = {"index": 0, "diagnostics": 0}

    async def index_status(
        provider: EmbeddingProvider,
        sources: list[IContextSearchSource],
    ) -> RagHealthState:
        calls["index"] += 1
        return RagHealthState.HEALTHY

    async def source_statuses(
        provider: EmbeddingProvider,
        sources: list[IContextSearchSource],
    ) -> list[ContextEmbeddingSourceStatus]:
        calls["diagnostics"] += 1
        raise AssertionError("recall health must not calculate detailed diagnostics")

    monkeypatch.setattr(health_module, "_embedding_index_status", index_status)
    monkeypatch.setattr(health_module, "_embedding_source_statuses", source_statuses)
    service = ContextEmbeddingHealthService(
        provider=_provider(),
        vector_retrieval_enabled=True,
        search_sources=[],
    )

    health = anyio.run(service.recall_health)

    assert health.embedding is RagHealthState.HEALTHY
    assert health.default_strategy is RagStrategy.HYBRID
    assert health.source_statuses == ()
    assert calls == {"index": 1, "diagnostics": 0}


def test_recall_health_preserves_reindex_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted fingerprint mismatch should still disable vector recall."""

    async def index_status(
        provider: EmbeddingProvider,
        sources: list[IContextSearchSource],
    ) -> RagHealthState:
        return RagHealthState.REINDEX_REQUIRED

    monkeypatch.setattr(health_module, "_embedding_index_status", index_status)
    service = ContextEmbeddingHealthService(
        provider=_provider(),
        vector_retrieval_enabled=True,
        search_sources=[],
    )

    health = anyio.run(service.recall_health)

    assert health.embedding is RagHealthState.REINDEX_REQUIRED
    assert health.default_strategy is RagStrategy.FTS_ONLY
    assert health.source_statuses == ()
    assert any("REINDEX_REQUIRED" in warning for warning in health.warnings)


def test_diagnostic_health_derives_index_status_from_source_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The status endpoint should calculate detailed diagnostics only once per source."""
    expected = ContextEmbeddingSourceStatus(
        source_name="obsidian_vault",
        status=RagHealthState.HEALTHY,
        total_rows=12,
        current_rows=12,
        stale_rows=0,
        missing_rows=0,
        current_fingerprint={},
        stored_fingerprints=(),
    )
    calls = {"diagnostics": 0}

    async def source_statuses(
        provider: EmbeddingProvider,
        sources: list[IContextSearchSource],
    ) -> list[ContextEmbeddingSourceStatus]:
        calls["diagnostics"] += 1
        return [expected]

    async def unexpected_index_status(
        provider: EmbeddingProvider,
        sources: list[IContextSearchSource],
    ) -> RagHealthState:
        raise AssertionError(
            "diagnostic health must derive status from source diagnostics"
        )

    monkeypatch.setattr(health_module, "_embedding_source_statuses", source_statuses)
    monkeypatch.setattr(
        health_module,
        "_embedding_index_status",
        unexpected_index_status,
    )
    service = ContextEmbeddingHealthService(
        provider=_provider(),
        vector_retrieval_enabled=True,
        search_sources=[],
    )

    health = anyio.run(service.health_with_index_status)

    assert health.embedding is RagHealthState.HEALTHY
    assert health.default_strategy is RagStrategy.HYBRID
    assert health.source_statuses == (expected,)
    assert calls == {"diagnostics": 1}
