"""Operator-only retrieval diagnostics HTTP contracts."""

from __future__ import annotations

import anyio
import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.main import app
from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchExecutionTrace,
    ContextSearchExplainResult,
    ContextSearchTimingTrace,
)
from app.memory.application.contexts.records.context_service_ports import (
    ContextSearchDiagnosticsPort,
)
from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    build_context_retrieval_plan,
)
from app.memory.domain.entities.context_read_models import ContextPack
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    MemoryFunction,
    RagStrategy,
)
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    ContextRetrievalFusionTrace,
)
from app.operations.application.diagnostics.operational_retrieval_diagnostics_service import (
    OperationalRetrievalDiagnosticsQuery,
    OperationalRetrievalDiagnosticsService,
)
from app.operations.interface.routers.retrieval_diagnostics_router import (
    explain_context_retrieval,
)
from app.operations.interface.schemas.operations.operational_retrieval_diagnostics_schema import (
    OperationalRetrievalExplainRequest,
)


class _FakeContextDiagnostics(ContextSearchDiagnosticsPort):
    def __init__(self) -> None:
        self.requests: list[OperationalRetrievalDiagnosticsQuery] = []

    async def explain_search(
        self,
        query: str,
        strategy: RagStrategy = RagStrategy.HYBRID,
        limit: int = 5,
        project: str | None = None,
        kind: ContextKind | None = None,
        include_scopes: list[ContextScope] | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None = None,
        prefer_memory_functions: list[MemoryFunction] | None = None,
    ) -> ContextSearchExplainResult:
        request = OperationalRetrievalDiagnosticsQuery(
            query=query,
            strategy=strategy,
            limit=limit,
            project=project,
            kind=kind,
            include_scopes=tuple(include_scopes or ()),
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            include_lifecycle_statuses=tuple(include_lifecycle_statuses or ()),
            prefer_memory_functions=tuple(prefer_memory_functions or ()),
        )
        self.requests.append(request)
        return _explained_result(request)


def test_retrieval_diagnostics_route_is_registered() -> None:
    """Application startup must expose the dedicated operator-only route."""
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/operations/retrieval/explain" in paths


def test_retrieval_diagnostics_handler_returns_bounded_metadata_only() -> None:
    """Operator response must omit Context bodies, embeddings, and rendered pack text."""
    context_service = _FakeContextDiagnostics()
    service = OperationalRetrievalDiagnosticsService(context_service)
    request = OperationalRetrievalExplainRequest(
        query="Engineering Harness",
        strategy=RagStrategy.HYBRID,
        limit=3,
        project="heterarchy-alexandria",
        include_scopes=[ContextScope.PROJECT],
    )

    async def scenario() -> dict[str, object]:
        response = await explain_context_retrieval(request=request, service=service)
        return response.model_dump(mode="json")

    payload = anyio.run(scenario)

    assert payload["query"] == "Engineering Harness"
    assert payload["strategy"] == "HYBRID"
    assert payload["effective_strategy"] == "HYBRID"
    assert payload["match_count"] == 0
    assert payload["context_pack_built"] is True
    assert payload["matches"] == []
    assert "context_pack" not in payload
    assert "content" not in payload
    assert "embedding" not in payload
    trace = payload["trace"]
    assert isinstance(trace, dict)
    assert trace["kernel_fusion"]["fused_candidate_count"] == 3
    assert trace["kernel_fusion"]["cross_lane_count"] == 1
    assert context_service.requests == [
        OperationalRetrievalDiagnosticsQuery(
            query="Engineering Harness",
            strategy=RagStrategy.HYBRID,
            limit=3,
            project="heterarchy-alexandria",
            include_scopes=(ContextScope.PROJECT,),
        )
    ]


def test_retrieval_diagnostics_auto_exposes_bounded_planner_metadata() -> None:
    """AUTO diagnostics should expose typed planner metadata without Context payloads."""
    context_service = _FakeContextDiagnostics()
    service = OperationalRetrievalDiagnosticsService(context_service)
    request = OperationalRetrievalExplainRequest(
        query="지금 최종 상태는 무엇인가?",
        strategy=RagStrategy.AUTO,
        limit=3,
        project="heterarchy-alexandria",
        include_scopes=[ContextScope.PROJECT],
    )

    async def scenario() -> dict[str, object]:
        response = await explain_context_retrieval(request=request, service=service)
        return response.model_dump(mode="json")

    payload = anyio.run(scenario)
    trace = payload["trace"]
    assert isinstance(trace, dict)
    plan = trace["retrieval_plan"]
    assert isinstance(plan, dict)
    assert plan["profile_version"] == "adaptive-retrieval-v1"
    assert plan["intent"] == "TEMPORAL_CURRENT_STATE"
    assert plan["strategy"] == "HYBRID"
    assert plan["fts_budget"] == 18
    assert plan["vector_budget"] == 18
    assert plan["graph_enabled"] is False
    assert plan["temporal_current_preference"] is True
    assert "content" not in plan
    assert "embedding" not in plan


def test_retrieval_diagnostics_request_is_strict_and_scope_aware() -> None:
    """Strict request validation must reject unknown fields and incomplete scope identity."""
    with pytest.raises(ValidationError):
        OperationalRetrievalExplainRequest.model_validate(
            {"query": "test", "unknown": True}
        )
    with pytest.raises(ValidationError, match="MISSING_AGENT_ID"):
        OperationalRetrievalExplainRequest(
            query="test",
            include_scopes=[ContextScope.AGENT],
        )


def _explained_result(
    request: OperationalRetrievalDiagnosticsQuery,
) -> ContextSearchExplainResult:
    pack = ContextPack(
        query=request.query,
        strategy=request.strategy,
        effective_strategy=request.strategy,
        warnings=(),
        recall_scopes=request.include_scopes,
        matches=(),
        context_pack="# Alexandria Context Pack\n",
    )
    fusion = ContextRetrievalFusionTrace(
        fts_input_count=2,
        vector_input_count=2,
        fts_unique_count=2,
        vector_unique_count=2,
        fts_duplicate_count=0,
        vector_duplicate_count=0,
        fused_candidate_count=3,
        cross_lane_count=1,
        returned_count=0,
        representative_fts_count=0,
        representative_vector_count=0,
    )
    timing = ContextSearchTimingTrace(
        embedding_health_ms=1.0,
        fts_ms=2.0,
        vector_ms=3.0,
        fusion_ms=0.5,
        filter_ms=0.1,
        graph_ms=0.2,
        context_pack_ms=0.3,
        total_ms=7.1,
    )
    trace = ContextSearchExecutionTrace(
        requested_strategy=request.strategy,
        effective_strategy=request.strategy,
        requested_limit=request.limit,
        hybrid_candidate_limit=18,
        fts_source_calls=1,
        fts_query_variants_attempted=1,
        fts_source_candidate_count=2,
        fts_ranked_candidate_count=2,
        vector_candidate_count=2,
        post_fusion_match_count=0,
        filtered_match_count=0,
        graph_evidence_match_count=0,
        graph_enrichment_applied=False,
        graph_enrichment_degraded=False,
        kernel_fusion=fusion,
        timings=timing,
        retrieval_plan=(
            build_context_retrieval_plan(
                request.query,
                request.limit,
                caller_memory_functions=request.prefer_memory_functions,
            )
            if request.strategy is RagStrategy.AUTO
            else None
        ),
    )
    return ContextSearchExplainResult(pack=pack, trace=trace)
