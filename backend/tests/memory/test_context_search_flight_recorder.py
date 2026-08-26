"""Explain-only Context retrieval flight-recorder contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
import pytest
from tests.memory.context_retrieval_kernel_test_provider import (
    create_test_context_retrieval_kernel_provider,
)

from app.memory.application.contexts.diagnostics import (
    context_search_trace as trace_module,
)
from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.contexts.records.context_search_service import (
    ContextSearchService,
)
from app.memory.domain.contracts.context_recall_contracts import ContextFtsRecall
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextRetrievalIntent,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.repositories.contexts.graph.context_graph_signal_provider import (
    ContextGraphEnrichmentResult,
    IContextGraphSignalProvider,
)
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    ContextRetrievalMergeTraceResult,
    IContextRetrievalKernelProvider,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload

NOW = datetime(2026, 8, 25, tzinfo=UTC)


class _FtsSource:
    def __init__(self, matches: list[ContextSearchMatch]) -> None:
        self.matches = matches
        self.queries: list[str] = []

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        self.queries.append(recall.query)
        return self.matches[: recall.recall_filter.limit]


class _EmbeddingService:
    def __init__(
        self,
        vector_matches: list[ContextSearchMatch],
        *,
        default_strategy: RagStrategy = RagStrategy.HYBRID,
    ) -> None:
        self.vector_matches = vector_matches
        self.default_strategy = default_strategy
        self.vector_calls = 0

    async def recall_health(self) -> RagDependencyHealth:
        healthy = self.default_strategy is RagStrategy.HYBRID
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY
            if healthy
            else RagHealthState.REINDEX_REQUIRED,
            embedding=RagHealthState.HEALTHY
            if healthy
            else RagHealthState.REINDEX_REQUIRED,
            default_strategy=self.default_strategy,
            model_name="test",
            dimensions=3,
            fingerprint=None,
            warnings=() if healthy else ("test vector degraded",),
        )

    async def search_vector(self, **kwargs: object) -> list[ContextSearchMatch]:
        del kwargs
        self.vector_calls += 1
        if self.default_strategy is RagStrategy.FTS_ONLY:
            raise AssertionError("degraded HYBRID must not execute vector search")
        return self.vector_matches


class _RecordingGraphSignals(IContextGraphSignalProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def enrich(
        self, matches: list[ContextSearchMatch]
    ) -> ContextGraphEnrichmentResult:
        self.calls += 1
        return ContextGraphEnrichmentResult(matches=tuple(matches))


class _RecordingKernel(IContextRetrievalKernelProvider):
    def __init__(self) -> None:
        self.delegate = create_test_context_retrieval_kernel_provider()
        self.merge_calls = 0
        self.trace_calls = 0

    @property
    def authority(self) -> str:
        return "test-recording"

    def hybrid_candidate_limit(self, limit: int) -> int:
        return self.delegate.hybrid_candidate_limit(limit)

    def merge(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        self.merge_calls += 1
        return self.delegate.merge(fts_matches, vector_matches, limit)

    def merge_with_trace(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> ContextRetrievalMergeTraceResult:
        self.trace_calls += 1
        return self.delegate.merge_with_trace(fts_matches, vector_matches, limit)

    def rank_best(
        self,
        matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        return self.delegate.rank_best(matches, limit)


def test_normal_search_does_not_collect_flight_recorder_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal recall must keep trace timing and traced native fusion off its fast path."""
    kernel = _RecordingKernel()
    service = _service(kernel=kernel)

    def unexpected_perf_counter() -> float:
        raise AssertionError("normal search must not collect flight-recorder timings")

    monkeypatch.setattr(trace_module, "perf_counter", unexpected_perf_counter)

    async def scenario() -> ContextPack:
        return await service.search(
            query="retrieval flight recorder",
            strategy=RagStrategy.HYBRID,
            limit=2,
            project="heterarchy-alexandria",
        )

    pack = anyio.run(scenario)

    assert isinstance(pack, ContextPack)
    assert kernel.merge_calls == 1
    assert kernel.trace_calls == 0


def test_explain_hybrid_preserves_results_and_reports_bounded_trace() -> None:
    """Explained HYBRID recall should execute one traced fusion with unchanged ranking."""
    kernel = _RecordingKernel()
    service = _service(kernel=kernel)

    async def baseline_scenario() -> ContextPack:
        return await service.search(
            query="retrieval flight recorder",
            strategy=RagStrategy.HYBRID,
            limit=2,
            project="heterarchy-alexandria",
        )

    async def explain_scenario():
        return await service.explain_search(
            query="retrieval flight recorder",
            strategy=RagStrategy.HYBRID,
            limit=2,
            project="heterarchy-alexandria",
        )

    baseline = anyio.run(baseline_scenario)
    explained = anyio.run(explain_scenario)

    assert [match.context.id for match in explained.pack.matches] == [
        match.context.id for match in baseline.matches
    ]
    assert [match.score for match in explained.pack.matches] == [
        match.score for match in baseline.matches
    ]
    trace = explained.trace
    assert trace.requested_strategy is RagStrategy.HYBRID
    assert trace.effective_strategy is RagStrategy.HYBRID
    assert trace.requested_limit == 2
    assert trace.hybrid_candidate_limit == 12
    assert trace.fts_source_calls == 1
    assert trace.fts_query_variants_attempted == 1
    assert trace.fts_source_candidate_count == 2
    assert trace.fts_ranked_candidate_count == 2
    assert trace.vector_candidate_count == 2
    assert trace.post_fusion_match_count == 2
    assert trace.filtered_match_count == 2
    assert trace.kernel_fusion is not None
    assert trace.kernel_fusion.fts_input_count == 2
    assert trace.kernel_fusion.vector_input_count == 2
    assert trace.kernel_fusion.fused_candidate_count == 3
    assert trace.kernel_fusion.cross_lane_count == 1
    assert trace.kernel_fusion.returned_count == 2
    assert kernel.merge_calls == 1
    assert kernel.trace_calls == 1
    assert all(
        value >= 0.0
        for value in (
            trace.timings.embedding_health_ms,
            trace.timings.fts_ms,
            trace.timings.vector_ms,
            trace.timings.fusion_ms,
            trace.timings.filter_ms,
            trace.timings.graph_ms,
            trace.timings.context_pack_ms,
            trace.timings.total_ms,
        )
    )


def test_explain_hybrid_degradation_reports_fts_without_fusion_trace() -> None:
    """Health degradation should remain visible without pretending native fusion ran."""
    kernel = _RecordingKernel()
    source = _FtsSource([_match("lexical", score=0.8, lane="fts")])
    embedding = _EmbeddingService([], default_strategy=RagStrategy.FTS_ONLY)
    service = ContextSearchService(
        search_sources=[cast(IContextSearchSource, source)],
        embedding_service=cast(ContextEmbeddingService, embedding),
        retrieval_kernel_provider=kernel,
    )

    async def scenario():
        return await service.explain_search(
            query="degraded vector recall",
            strategy=RagStrategy.HYBRID,
            limit=3,
            project="heterarchy-alexandria",
        )

    explained = anyio.run(scenario)

    assert explained.pack.effective_strategy is RagStrategy.FTS_ONLY
    assert explained.trace.effective_strategy is RagStrategy.FTS_ONLY
    assert explained.trace.kernel_fusion is None
    assert explained.trace.vector_candidate_count == 0
    assert explained.trace.fts_source_candidate_count == 1
    assert explained.trace.post_fusion_match_count == 1
    assert embedding.vector_calls == 0
    assert kernel.merge_calls == 0
    assert kernel.trace_calls == 0


def test_explain_auto_exact_uses_fts_only_and_records_plan() -> None:
    """AUTO exact/title lookup should avoid vector and expose the deterministic plan."""
    kernel = _RecordingKernel()
    source = _FtsSource([_match("lexical", score=0.8, lane="fts")])
    embedding = _EmbeddingService([_match("semantic", score=0.9, lane="vector")])
    service = ContextSearchService(
        search_sources=[cast(IContextSearchSource, source)],
        embedding_service=cast(ContextEmbeddingService, embedding),
        retrieval_kernel_provider=kernel,
    )

    explained = anyio.run(
        service.explain_search,
        "Alexandria Memory Steward Contract",
        RagStrategy.AUTO,
        3,
        "heterarchy-alexandria",
    )

    assert explained.pack.strategy is RagStrategy.AUTO
    assert explained.pack.effective_strategy is RagStrategy.FTS_ONLY
    assert embedding.vector_calls == 0
    assert kernel.trace_calls == 0
    assert explained.trace.retrieval_plan is not None
    assert (
        explained.trace.retrieval_plan.intent is ContextRetrievalIntent.EXACT_OR_TITLE
    )
    assert explained.trace.retrieval_plan.strategy is RagStrategy.FTS_ONLY
    assert explained.trace.retrieval_plan.fts_budget == 3
    assert explained.trace.retrieval_plan.vector_budget == 0


def test_explain_auto_semantic_uses_hybrid_and_degrades_with_existing_health_policy() -> (
    None
):
    """AUTO semantic recall should reuse Hybrid fusion and the established FTS degradation."""
    healthy_kernel = _RecordingKernel()
    healthy = _service(kernel=healthy_kernel)
    explained = anyio.run(
        healthy.explain_search,
        "왜 retrieval quality가 떨어졌는지 설명해줘?",
        RagStrategy.AUTO,
        2,
        "heterarchy-alexandria",
    )

    assert explained.pack.strategy is RagStrategy.AUTO
    assert explained.pack.effective_strategy is RagStrategy.HYBRID
    assert explained.trace.kernel_fusion is not None
    assert explained.trace.retrieval_plan is not None
    assert (
        explained.trace.retrieval_plan.intent
        is ContextRetrievalIntent.SEMANTIC_PARAPHRASE
    )
    assert healthy_kernel.trace_calls == 1

    degraded_kernel = _RecordingKernel()
    degraded_embedding = _EmbeddingService([], default_strategy=RagStrategy.FTS_ONLY)
    degraded = ContextSearchService(
        search_sources=[
            cast(
                IContextSearchSource,
                _FtsSource([_match("lexical", score=0.8, lane="fts")]),
            )
        ],
        embedding_service=cast(ContextEmbeddingService, degraded_embedding),
        retrieval_kernel_provider=degraded_kernel,
    )
    degraded_explained = anyio.run(
        degraded.explain_search,
        "왜 retrieval quality가 떨어졌는지 설명해줘?",
        RagStrategy.AUTO,
        2,
        "heterarchy-alexandria",
    )

    assert degraded_explained.pack.effective_strategy is RagStrategy.FTS_ONLY
    assert degraded_explained.trace.retrieval_plan is not None
    assert degraded_explained.trace.retrieval_plan.strategy is RagStrategy.HYBRID
    assert degraded_embedding.vector_calls == 0
    assert degraded_kernel.trace_calls == 0


def test_auto_graph_lane_runs_only_for_explicit_graph_intent() -> None:
    """AUTO should skip graph I/O unless the deterministic plan requests graph evidence."""
    graph = _RecordingGraphSignals()
    kernel = _RecordingKernel()
    service = _service(kernel=kernel, graph_signal_provider=graph)

    anyio.run(
        service.search,
        "왜 retrieval quality가 떨어졌는지 설명해줘?",
        RagStrategy.AUTO,
        2,
        "heterarchy-alexandria",
    )
    assert graph.calls == 0

    graph_pack = anyio.run(
        service.search,
        "이 기억은 무엇과 관련되어 있고 어떤 관계가 있나?",
        RagStrategy.AUTO,
        2,
        "heterarchy-alexandria",
    )
    assert graph.calls == 1
    assert graph_pack.strategy is RagStrategy.AUTO
    assert graph_pack.effective_strategy is RagStrategy.HYBRID


def _service(
    kernel: _RecordingKernel,
    graph_signal_provider: IContextGraphSignalProvider | None = None,
) -> ContextSearchService:
    fts = [
        _match("dual", score=0.9, lane="fts"),
        _match("lexical", score=0.8, lane="fts"),
    ]
    vector = [
        _match("semantic", score=0.99, lane="vector"),
        _match("dual", score=0.95, lane="vector"),
    ]
    return ContextSearchService(
        search_sources=[cast(IContextSearchSource, _FtsSource(fts))],
        embedding_service=cast(ContextEmbeddingService, _EmbeddingService(vector)),
        retrieval_kernel_provider=kernel,
        graph_signal_provider=graph_signal_provider,
    )


def _match(note_id: str, *, score: float, lane: str) -> ContextSearchMatch:
    context = ContextRecord(
        id=note_id,
        kind=ContextKind.HANDOFF,
        title=note_id.title(),
        summary="summary",
        content="content",
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="test",
        source_type=ContextSourceType.IMPORTED,
        importance=ContextImportance.HIGH,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata=ContextMetadataPayload(canonical_context_id=note_id),
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{note_id}",
        context_id=note_id,
        chunk_index=0,
        heading=None,
        content="content",
        token_count=1,
        content_hash=f"hash-{note_id}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=score if lane == "fts" else None,
        vector_score=score if lane == "vector" else None,
        why_retrieved="PostgreSQL retrieval evidence.",
    )
