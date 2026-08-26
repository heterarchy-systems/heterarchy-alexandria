"""Flight-recorder contracts for AUTO multi-hop graph candidate expansion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
from tests.memory.context_retrieval_kernel_test_provider import (
    create_test_context_retrieval_kernel_provider,
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
    ContextEmbeddingSourceStatus,
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
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_expansion_provider import (
    ContextGraphCandidateExpansionResult,
    IContextGraphCandidateExpansionProvider,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.types.extra_types import JSONObject

_NOW = datetime(2026, 8, 26, tzinfo=UTC)


class _SearchSource:
    def __init__(self, matches: list[ContextSearchMatch]) -> None:
        self._matches = matches

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        return self._matches[: recall.recall_filter.limit]


class _EmbeddingService:
    def __init__(self, matches: list[ContextSearchMatch]) -> None:
        self._matches = matches

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
        del kwargs
        return self._matches

    async def embedding_source_status(
        self,
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        del model_name, dimensions, fingerprint_key, current_fingerprint
        raise AssertionError("not used by graph expansion flight-recorder tests")


class _Expansion(IContextGraphCandidateExpansionProvider):
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    async def expand(
        self,
        query: str,
        matches: list[ContextSearchMatch],
        recall_filter,
        limit: int,
        graph_depth: int,
    ) -> ContextGraphCandidateExpansionResult:
        del query, recall_filter, graph_depth
        if self._fail:
            raise RuntimeError("graph expansion unavailable")
        graph_match = _match("graph-target", 0.95)
        graph_match.fts_score = None
        graph_match.graph_score = 0.95
        return ContextGraphCandidateExpansionResult(
            matches=tuple([graph_match, *matches][:limit]),
            discovered_candidate_count=4,
            selected_candidate_count=2,
            hydrated_candidate_count=1,
            filtered_candidate_count=1,
            appended_candidate_count=1,
        )


def test_explain_search_reports_bounded_graph_expansion_counters() -> None:
    result = anyio.run(_explain, _Expansion())

    trace = result.trace
    assert trace.graph_expansion_discovered_candidate_count == 4
    assert trace.graph_expansion_selected_candidate_count == 2
    assert trace.graph_expansion_hydrated_candidate_count == 1
    assert trace.graph_expansion_filtered_candidate_count == 1
    assert trace.graph_expansion_appended_candidate_count == 1
    assert trace.graph_expansion_applied is True
    assert trace.graph_expansion_degraded is False
    assert trace.timings.graph_expansion_ms >= 0.0


def test_explain_search_marks_graph_expansion_degraded_and_preserves_primary() -> None:
    result = anyio.run(_explain, _Expansion(fail=True))

    assert [match.context.id for match in result.pack.matches] == [
        "primary-a",
        "primary-b",
    ]
    assert result.trace.graph_expansion_degraded is True
    assert result.trace.graph_expansion_applied is False
    assert result.trace.graph_expansion_appended_candidate_count == 0
    assert "GRAPH_EXPANSION_UNAVAILABLE" in " ".join(result.pack.warnings)


async def _explain(expansion: IContextGraphCandidateExpansionProvider):
    matches = [_match("primary-a", 0.9), _match("primary-b", 0.8)]
    service = ContextSearchService(
        search_sources=[cast(IContextSearchSource, _SearchSource(matches))],
        embedding_service=cast(ContextEmbeddingService, _EmbeddingService(matches)),
        retrieval_kernel_provider=create_test_context_retrieval_kernel_provider(),
        graph_candidate_expansion_provider=expansion,
    )
    return await service.explain_search(
        "이 기억은 무엇과 관련되어 있고 어떤 관계가 있나?",
        strategy=RagStrategy.AUTO,
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
        context_metadata=ContextMetadataPayload(
            canonical_context_id=note_id,
            obsidian_note_id=note_id,
        ),
        created_at=_NOW,
        updated_at=_NOW,
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
        created_at=_NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=score,
        vector_score=None,
        why_retrieved="Primary retrieval evidence.",
    )
