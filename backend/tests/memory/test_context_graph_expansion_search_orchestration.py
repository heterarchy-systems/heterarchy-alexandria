"""Search orchestration contracts for AUTO-only multi-hop graph expansion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio

from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.contexts.records.context_search_service import (
    ContextSearchService,
)
from app.memory.domain.contracts.context_recall_contracts import ContextFtsRecall
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    IContextRetrievalKernelProvider,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_expansion_provider import (
    ContextGraphCandidateExpansionResult,
    IContextGraphCandidateExpansionProvider,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.types.extra_types import JSONObject

NOW = datetime(2026, 8, 26, tzinfo=UTC)


class _FtsSource:
    def __init__(self, matches: list[ContextSearchMatch]) -> None:
        self.matches = matches

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        return self.matches[: recall.recall_filter.limit]


class _EmbeddingService:
    def __init__(self, matches: list[ContextSearchMatch]) -> None:
        self.matches = matches

    async def recall_health(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.HEALTHY,
            default_strategy=RagStrategy.HYBRID,
            model_name="test",
            dimensions=3,
            fingerprint=None,
            warnings=(),
        )

    async def search_vector(self, **kwargs: object) -> list[ContextSearchMatch]:
        return self.matches

    async def embedding_source_status(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        raise AssertionError("not used by retrieval orchestration tests")


class _Kernel:
    @property
    def authority(self) -> str:
        return "test"

    def hybrid_candidate_limit(self, limit: int) -> int:
        return min(50, max(limit, limit * 6))

    def merge(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        merged: list[ContextSearchMatch] = []
        seen: set[str] = set()
        for match in [*fts_matches, *vector_matches]:
            if match.context.id in seen:
                continue
            seen.add(match.context.id)
            merged.append(match)
        return merged[:limit]

    def rank_best(
        self,
        matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        return sorted(matches, key=lambda match: match.score, reverse=True)[:limit]


class _RecordingExpansion(IContextGraphCandidateExpansionProvider):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...], int, int]] = []

    async def expand(
        self,
        query: str,
        matches: list[ContextSearchMatch],
        recall_filter,
        limit: int,
        graph_depth: int,
    ) -> ContextGraphCandidateExpansionResult:
        del recall_filter
        self.calls.append(
            (query, tuple(match.context.id for match in matches), limit, graph_depth)
        )
        if self.fail:
            raise RuntimeError("graphdb://reader:super-secret@example.test")
        return ContextGraphCandidateExpansionResult(matches=tuple(matches[:limit]))


def test_auto_graph_intent_invokes_multi_hop_expansion_once() -> None:
    expansion = _RecordingExpansion()

    pack = anyio.run(
        _search,
        "이 기억은 무엇과 관련되어 있고 어떤 관계가 있나?",
        RagStrategy.AUTO,
        expansion,
    )

    assert len(expansion.calls) == 1
    assert expansion.calls[0][0].startswith("이 기억은")
    assert expansion.calls[0][2] == 5
    assert expansion.calls[0][3] == 2
    assert pack.strategy is RagStrategy.AUTO


def test_fixed_hybrid_graph_query_does_not_invoke_multi_hop_expansion() -> None:
    expansion = _RecordingExpansion()

    pack = anyio.run(
        _search,
        "이 기억은 무엇과 관련되어 있고 어떤 관계가 있나?",
        RagStrategy.HYBRID,
        expansion,
    )

    assert expansion.calls == []
    assert pack.strategy is RagStrategy.HYBRID


def test_auto_non_graph_query_does_not_invoke_multi_hop_expansion() -> None:
    expansion = _RecordingExpansion()

    anyio.run(
        _search,
        "왜 retrieval quality가 떨어졌는지 설명해줘?",
        RagStrategy.AUTO,
        expansion,
    )

    assert expansion.calls == []


def test_auto_graph_expansion_failure_preserves_primary_and_sanitizes_warning() -> None:
    expansion = _RecordingExpansion(fail=True)

    pack = anyio.run(
        _search,
        "이 기억은 무엇과 관련되어 있고 어떤 관계가 있나?",
        RagStrategy.AUTO,
        expansion,
    )

    assert len(expansion.calls) == 1
    assert [match.context.id for match in pack.matches] == ["primary-a", "primary-b"]
    rendered = " ".join(pack.warnings)
    assert "GRAPH_EXPANSION_UNAVAILABLE" in rendered
    assert "RuntimeError" in rendered
    assert "super-secret" not in rendered
    assert "graphdb://" not in rendered


async def _search(
    query: str,
    strategy: RagStrategy,
    expansion: IContextGraphCandidateExpansionProvider,
) -> ContextPack:
    matches = [_match("primary-a", 0.9), _match("primary-b", 0.8)]
    service = ContextSearchService(
        search_sources=[cast(IContextSearchSource, _FtsSource(matches))],
        embedding_service=cast(ContextEmbeddingService, _EmbeddingService(matches)),
        retrieval_kernel_provider=cast(IContextRetrievalKernelProvider, _Kernel()),
        graph_candidate_expansion_provider=expansion,
    )
    return await service.search(
        query,
        strategy=strategy,
        project="heterarchy-alexandria",
        limit=5,
    )


def _match(note_id: str, score: float) -> ContextSearchMatch:
    context = ContextRecord(
        id=note_id,
        kind=ContextKind.HANDOFF,
        title=note_id.replace("-", " ").title(),
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
        content=f"{note_id} content",
        token_count=3,
        content_hash=f"hash-{note_id}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=score,
        vector_score=None,
        why_retrieved="Primary retrieval evidence.",
    )
