"""Public historical recall cascade regression coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import anyio
from test_high_level_recall import _match

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.recall.recall_service import RecallService
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelector,
    RecallExactSelectorResolver,
    RecallRequest,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.entities.memory_reconciliation import (
    MemoryTemporalRecallMatch,
    MemoryTemporalRecallPack,
    MemoryTemporalState,
)
from app.memory.domain.entities.recall import RecallResult
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.memory.interface.schemas.context.recall_response_schema import (
    RecallResponseSchema,
)

AS_OF = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class _HistoricalTemporalFake:
    """Return a typed temporal pack based on the requested project lane."""

    def __init__(
        self,
        *,
        related_project: str,
        related_match: ContextSearchMatch,
    ) -> None:
        self.related_project = related_project
        self.related_match = related_match
        self.requests: list[MemoryTemporalRecallRequest] = []

    async def recall(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        self.requests.append(request)
        matches = (
            (
                MemoryTemporalRecallMatch(
                    match=self.related_match,
                    temporal_state=MemoryTemporalState(
                        context_id=self.related_match.context.id,
                        recorded_at=AS_OF,
                        observed_at=AS_OF,
                        valid_from=AS_OF,
                        valid_to=None,
                        is_current=False,
                    ),
                    is_current=False,
                ),
            )
            if request.project == self.related_project
            else ()
        )
        return MemoryTemporalRecallPack(
            query=request.query,
            mode=request.mode,
            as_of=request.as_of,
            strategy=request.strategy,
            effective_strategy=request.strategy,
            warnings=(),
            recall_scopes=request.include_scopes,
            matches=matches,
            context_pack=("Historical related memory." if matches else ""),
        )


class _RecordingExactSelectorResolver:
    """Track any attempt to resolve the exact selector through canonical identity."""

    def __init__(self) -> None:
        self.calls: list[tuple[RecallExactSelector, ScopeIdentity]] = []

    async def resolve(
        self,
        selector: RecallExactSelector,
        scope_identity: ScopeIdentity,
    ) -> tuple[ContextSearchMatch, ...]:
        self.calls.append((selector, scope_identity))
        return ()


def test_historical_strict_project_cascade_stops_on_confident_related_match() -> None:
    primary_project = "alexandria"
    first_related_project = "forge"
    remaining_related_project = "orchestration"
    related_match = _match(
        "related-context",
        project=first_related_project,
        score=0.9,
        fts_score=0.9,
    )
    temporal = _HistoricalTemporalFake(
        related_project=first_related_project,
        related_match=related_match,
    )
    exact_resolver = _RecordingExactSelectorResolver()
    current_context_service = AsyncMock(spec=ContextService)
    service = RecallService(
        cast(ContextService, current_context_service),
        temporal_recall_service=cast(MemoryTemporalRecallService, temporal),
        exact_selector_resolver=cast(RecallExactSelectorResolver, exact_resolver),
    )
    request = RecallRequest(
        query="  historical architecture decision  ",
        limit=7,
        scope_mode=RecallScopeMode.STRICT,
        include_scopes=(ContextScope.PROJECT,),
        project=primary_project,
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        session_id="session-1",
        related_projects=(first_related_project, remaining_related_project),
        selector=RecallExactSelector(note_id="canonical-note-1"),
        as_of=AS_OF,
        kind=ContextKind.MEMORY,
        include_lifecycle_statuses=(
            ContextRecallLifecycleStatus.SUPERSEDED,
            ContextRecallLifecycleStatus.ARCHIVED,
        ),
    )

    async def scenario() -> RecallResult:
        return await service.recall(request)

    result = anyio.run(scenario)

    assert exact_resolver.calls == []
    current_context_service.explain_search.assert_not_awaited()
    assert [temporal_request.project for temporal_request in temporal.requests] == [
        primary_project,
        first_related_project,
    ]
    for temporal_request, project in zip(
        temporal.requests,
        (primary_project, first_related_project),
        strict=True,
    ):
        assert temporal_request.query == "historical architecture decision"
        assert temporal_request.mode is MemoryTemporalRecallMode.HISTORICAL
        assert temporal_request.as_of == AS_OF
        assert temporal_request.strategy is RagStrategy.HYBRID
        assert temporal_request.limit == 7
        assert temporal_request.project == project
        assert temporal_request.kind is ContextKind.MEMORY
        assert temporal_request.include_scopes == (ContextScope.PROJECT,)
        assert temporal_request.workspace_id == "workspace-1"
        assert temporal_request.agent_id == "agent-1"
        assert temporal_request.user_id == "user-1"
        assert temporal_request.session_id == "session-1"
        assert temporal_request.include_lifecycle_statuses == (
            ContextRecallLifecycleStatus.SUPERSEDED,
            ContextRecallLifecycleStatus.ARCHIVED,
        )

    assert result.query == "historical architecture decision"
    assert result.scope_mode is RecallScopeMode.STRICT
    assert result.recall_scopes == (ContextScope.PROJECT,)
    assert result.outcome is RecallOutcome.MATCHED
    assert [stage.route for stage in result.trace.stages] == [
        RecallRoute.EXACT_SELECTOR,
        RecallRoute.TEMPORAL_HISTORICAL,
        RecallRoute.TEMPORAL_HISTORICAL,
    ]
    assert [stage.status for stage in result.trace.stages] == [
        RecallStageStatus.SKIPPED,
        RecallStageStatus.ATTEMPTED,
        RecallStageStatus.ATTEMPTED,
    ]
    assert [stage.project for stage in result.trace.stages] == [
        None,
        primary_project,
        first_related_project,
    ]
    assert result.trace.fallback_expansion == (
        RecallRoute.TEMPORAL_HISTORICAL,
        RecallRoute.TEMPORAL_HISTORICAL,
    )
    assert len(result.matches) == 1
    related_provenance = result.matches[0].provenance
    assert related_provenance.route is RecallRoute.TEMPORAL_HISTORICAL
    assert related_provenance.project_affinity is RecallProjectAffinity.RELATED
    assert related_provenance.confidence >= 0.5
    assert related_provenance.temporal_eligible is True

    serialized = RecallResponseSchema.from_entity(result).model_dump(mode="json")
    assert set(serialized) == {
        "query",
        "scope_mode",
        "recall_scopes",
        "effective_strategy",
        "outcome",
        "warnings",
        "matches",
        "context_pack",
        "trace",
    }
    assert serialized["query"] == "historical architecture decision"
    assert serialized["scope_mode"] == "STRICT"
    assert serialized["recall_scopes"] == ["PROJECT"]
    assert serialized["outcome"] == "MATCHED"
    assert serialized["matches"][0]["provenance"]["route"] == ("TEMPORAL_HISTORICAL")
    assert serialized["matches"][0]["provenance"]["project_affinity"] == "RELATED"
    assert serialized["matches"][0]["provenance"]["temporal_eligible"] is True
    serialized_stages = serialized["trace"]["stages"]
    assert [stage["route"] for stage in serialized_stages] == [
        "EXACT_SELECTOR",
        "TEMPORAL_HISTORICAL",
        "TEMPORAL_HISTORICAL",
    ]
    assert "project" not in serialized_stages[0]
    assert [stage["project"] for stage in serialized_stages[1:]] == [
        primary_project,
        first_related_project,
    ]
