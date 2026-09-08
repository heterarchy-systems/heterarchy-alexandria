"""Focused regression tests for the high-level recall cascade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import anyio
import pytest

from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchExplainResult,
)
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.recall_service import RecallService
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelector,
    RecallRequest,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryTemporalRecallMatch,
    MemoryTemporalRecallPack,
    MemoryTemporalState,
)
from app.memory.domain.entities.recall import RecallResult
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallRoute,
    RecallScopeMode,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Explain:
    pack: ContextPack


class _SearchFake:
    """Typed fake for the existing Context search authority."""

    def __init__(
        self,
        result: Callable[[RagStrategy, str | None], list[ContextSearchMatch]],
        *,
        degraded_vector: bool = False,
    ) -> None:
        self._result = result
        self._degraded_vector = degraded_vector
        self.calls: list[tuple[RagStrategy, str | None, tuple[ContextScope, ...]]] = []

    async def explain_search(
        self,
        *,
        query: str,
        strategy: RagStrategy,
        limit: int,
        project: str | None,
        kind: ContextKind | None,
        include_scopes: list[ContextScope],
        workspace_id: str | None,
        agent_id: str | None,
        user_id: str | None,
        session_id: str | None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None,
    ) -> ContextSearchExplainResult:
        _ = (
            kind,
            limit,
            workspace_id,
            agent_id,
            user_id,
            session_id,
            include_lifecycle_statuses,
        )
        self.calls.append((strategy, project, tuple(include_scopes)))
        matches = self._result(strategy, project)
        effective_strategy = (
            RagStrategy.FTS_ONLY
            if self._degraded_vector and strategy is RagStrategy.VECTOR_ONLY
            else strategy
        )
        return cast(
            ContextSearchExplainResult,
            _Explain(
                pack=ContextPack(
                    query=query,
                    strategy=strategy,
                    effective_strategy=effective_strategy,
                    warnings=(
                        ("Vector retrieval degraded; using FTS_ONLY.",)
                        if effective_strategy is RagStrategy.FTS_ONLY
                        and strategy is RagStrategy.VECTOR_ONLY
                        else ()
                    ),
                    recall_scopes=tuple(include_scopes),
                    matches=tuple(matches),
                    context_pack="",
                )
            ),
        )


class _TemporalFake:
    """Typed fake for the existing temporal recall authority."""

    def __init__(self, pack: MemoryTemporalRecallPack) -> None:
        self.pack = pack
        self.requests: list[MemoryTemporalRecallRequest] = []
        self.view_requests: list[MemoryTemporalRecallRequest] = []

    async def recall(
        self, request: MemoryTemporalRecallRequest
    ) -> MemoryTemporalRecallPack:
        self.requests.append(request)
        return self.pack

    async def apply_view(
        self,
        pack: ContextPack,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        self.view_requests.append(request)
        return MemoryTemporalRecallPack(
            query=pack.query,
            mode=request.mode,
            as_of=request.as_of,
            strategy=pack.strategy,
            effective_strategy=pack.effective_strategy,
            warnings=pack.warnings,
            recall_scopes=pack.recall_scopes,
            matches=tuple(
                MemoryTemporalRecallMatch(
                    match=match,
                    temporal_state=None,
                    is_current=True,
                )
                for match in pack.matches
            ),
            context_pack=pack.context_pack,
        )


class _ExactEmpty:
    """Typed exact selector fake for non-selector cascade tests."""

    async def resolve(
        self,
        selector: RecallExactSelector,
        scope_identity: ScopeIdentity,
    ) -> tuple[ContextSearchMatch, ...]:
        del selector, scope_identity
        return ()


class _ExactOne:
    """Typed exact selector fake returning one source-backed Context match."""

    def __init__(self, match: ContextSearchMatch) -> None:
        self.match = match

    async def resolve(
        self,
        selector: RecallExactSelector,
        scope_identity: ScopeIdentity,
    ) -> tuple[ContextSearchMatch, ...]:
        del selector, scope_identity
        return (self.match,)


class _TemporalFailure:
    """Typed temporal collaborator failure used for exact-read degradation proof."""

    async def apply_view(
        self,
        pack: ContextPack,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        del pack, request
        raise RuntimeError("temporal projection unavailable")

    async def recall(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        del request
        raise RuntimeError("temporal projection unavailable")


def _match(
    context_id: str,
    *,
    project: str | None = "primary",
    score: float = 0.8,
    fts_score: float | None = 0.8,
    vector_score: float | None = None,
) -> ContextSearchMatch:
    context = ContextRecord(
        id=context_id,
        kind=ContextKind.MEMORY,
        title=f"Memory {context_id}",
        summary="A durable memory.",
        content="A durable memory body.",
        content_format=ContextContentFormat.MARKDOWN,
        project=project,
        scope=ContextScope.PROJECT if project else ContextScope.GLOBAL,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT if project else ContextScope.GLOBAL,
        source_agent="test",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.MEDIUM,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata={
            "lifecycle_status": "CURRENT",
            "source_revision": "source-1",
            "index_revision": "index-1",
        },
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    return ContextSearchMatch(
        context=context,
        chunk=ContextChunkRecord(
            id=f"chunk-{context_id}",
            context_id=context_id,
            chunk_index=0,
            heading="Current",
            content=context.content,
            token_count=4,
            content_hash=f"hash-{context_id}",
            chunk_metadata={},
            created_at=NOW,
        ),
        score=score,
        fts_score=fts_score,
        vector_score=vector_score,
        why_retrieved="test evidence",
    )


def _service(
    search: _SearchFake,
    temporal: _TemporalFake | None = None,
) -> RecallService:
    temporal_service = temporal or _TemporalFake(
        MemoryTemporalRecallPack(
            query="",
            mode=MemoryTemporalRecallMode.CURRENT,
            as_of=None,
            strategy=RagStrategy.HYBRID,
            effective_strategy=RagStrategy.HYBRID,
            warnings=(),
            recall_scopes=(ContextScope.GLOBAL,),
            matches=(),
            context_pack="",
        )
    )
    return RecallService(
        cast(ContextService, search),
        temporal_recall_service=cast(MemoryTemporalRecallService, temporal_service),
        exact_selector_resolver=_ExactEmpty(),
    )


def test_auto_skips_unavailable_identity_lanes_and_strict_rejects_missing_identity() -> (
    None
):
    search = _SearchFake(lambda _strategy, _project: [])
    service = _service(search)

    async def scenario() -> None:
        auto = await service.recall(RecallRequest(query="missing identity"))
        assert auto.outcome is RecallOutcome.SEARCH_EXHAUSTED
        assert "PROJECT:identity_unavailable" in auto.trace.skipped_scopes
        assert "USER:identity_unavailable" in auto.trace.skipped_scopes
        with pytest.raises(MemoryContextValidationError, match="MISSING_PROJECT"):
            await service.recall(
                RecallRequest(
                    query="strict project",
                    scope_mode=RecallScopeMode.STRICT,
                    include_scopes=(ContextScope.PROJECT,),
                )
            )

    anyio.run(scenario)
    assert search.calls
    assert all(ContextScope.PROJECT not in call[2] for call in search.calls)


def test_semantic_lane_is_attempted_after_empty_fts() -> None:
    semantic = _match("semantic", score=0.9, fts_score=None, vector_score=0.9)
    search = _SearchFake(
        lambda strategy, _project: (
            [] if strategy is RagStrategy.FTS_ONLY else [semantic]
        )
    )

    async def scenario() -> RecallResult:
        return await _service(search).recall(
            RecallRequest(query="paraphrased explanation", project="primary")
        )

    result = anyio.run(scenario)
    assert result.outcome is RecallOutcome.MATCHED
    assert [call[0] for call in search.calls[:2]] == [
        RagStrategy.FTS_ONLY,
        RagStrategy.VECTOR_ONLY,
    ]
    assert result.trace.stages[2].route is RecallRoute.PRIMARY_SEMANTIC


def test_related_project_expansion_is_bounded_and_reports_affinity() -> None:
    related = _match("related", project="forge", score=0.85)

    def result(strategy: RagStrategy, project: str | None) -> list[ContextSearchMatch]:
        return [related] if project == "forge" else []

    search = _SearchFake(result)

    async def scenario() -> RecallResult:
        return await _service(search).recall(
            RecallRequest(
                query="defect evidence",
                project="alexandria",
                related_projects=("forge", "unused-1", "unused-2", "unused-3"),
            )
        )

    result_value = anyio.run(scenario)
    assert result_value.outcome is RecallOutcome.MATCHED
    assert result_value.matches[0].provenance.project_affinity.value == "RELATED"
    assert "forge" in [call[1] for call in search.calls]
    assert "unused-1" not in [call[1] for call in search.calls]
    assert "unused-3" not in [call[1] for call in search.calls]

    with pytest.raises(MemoryContextValidationError, match="at most 4"):
        anyio.run(
            lambda: _service(search).recall(
                RecallRequest(
                    query="bounded",
                    related_projects=("a", "b", "c", "d", "e"),
                )
            )
        )


def test_failure_outcome_is_degraded_and_does_not_raise_as_success() -> None:
    def fail(_strategy: RagStrategy, _project: str | None) -> list[ContextSearchMatch]:
        raise RuntimeError("vector unavailable")

    search = _SearchFake(fail)

    async def scenario() -> RecallResult:
        return await _service(search).recall(
            RecallRequest(query="degraded retrieval", project="primary")
        )

    result = anyio.run(scenario)
    assert result.outcome is RecallOutcome.DEGRADED_SEARCH
    assert result.trace.degraded_subsystems
    assert result.warnings


def test_empty_fts_vector_only_fallback_reports_vector_degradation() -> None:
    search = _SearchFake(
        lambda _strategy, _project: [],
        degraded_vector=True,
    )

    async def scenario() -> RecallResult:
        return await _service(search).recall(
            RecallRequest(query="degraded vector", project="primary")
        )

    result = anyio.run(scenario)
    semantic_stage = next(
        stage
        for stage in result.trace.stages
        if stage.route is RecallRoute.PRIMARY_SEMANTIC
    )
    assert result.outcome is RecallOutcome.DEGRADED_SEARCH
    assert semantic_stage.effective_strategy is RagStrategy.FTS_ONLY
    assert semantic_stage.degraded is True


def test_historical_recall_uses_temporal_authority_and_history_lifecycle_filter() -> (
    None
):
    historical_match = _match("old", project="primary", score=0.9)
    state = MemoryTemporalState(
        context_id="old",
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=None,
        is_current=False,
    )
    temporal = _TemporalFake(
        MemoryTemporalRecallPack(
            query="old architecture",
            mode=MemoryTemporalRecallMode.HISTORICAL,
            as_of=NOW,
            strategy=RagStrategy.HYBRID,
            effective_strategy=RagStrategy.HYBRID,
            warnings=(),
            recall_scopes=(ContextScope.PROJECT,),
            matches=(
                MemoryTemporalRecallMatch(
                    match=historical_match,
                    temporal_state=state,
                    is_current=False,
                ),
            ),
            context_pack="historical",
        )
    )
    search = _SearchFake(lambda _strategy, _project: [])

    async def scenario() -> RecallResult:
        return await _service(search, temporal).recall(
            RecallRequest(
                query="old architecture",
                project="primary",
                as_of=NOW,
            )
        )

    result = anyio.run(scenario)
    assert result.outcome is RecallOutcome.MATCHED
    assert not search.calls
    assert temporal.requests[0].mode is MemoryTemporalRecallMode.HISTORICAL
    assert (
        ContextRecallLifecycleStatus.SUPERSEDED
        in temporal.requests[0].include_lifecycle_statuses
    )


def test_exact_source_survives_optional_temporal_projection_failure() -> None:
    match = _match("exact-source")
    search = _SearchFake(lambda _strategy, _project: [])
    service = RecallService(
        cast(ContextService, search),
        temporal_recall_service=cast(MemoryTemporalRecallService, _TemporalFailure()),
        exact_selector_resolver=_ExactOne(match),
    )

    async def scenario() -> RecallResult:
        return await service.recall(
            RecallRequest(
                query="exact source",
                project="primary",
                selector=RecallExactSelector(note_id="exact-source"),
            )
        )

    result = anyio.run(scenario)
    assert result.outcome is RecallOutcome.MATCHED
    assert result.trace.degraded_subsystems == ("exact_source",)
    assert result.matches[0].provenance.temporal_eligible is None
