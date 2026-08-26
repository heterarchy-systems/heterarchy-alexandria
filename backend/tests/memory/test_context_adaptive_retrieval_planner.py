"""Deterministic Phase 8 adaptive Context retrieval planner tests."""

from __future__ import annotations

import pytest

from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ADAPTIVE_RETRIEVAL_PROFILE_VERSION,
    ContextRetrievalPlan,
    build_context_retrieval_plan,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRetrievalFusionProfile,
    ContextRetrievalIntent,
    MemoryFunction,
    RagStrategy,
)


@pytest.mark.parametrize(
    ("query", "intent", "strategy", "graph_enabled", "preferred"),
    [
        (
            "Alexandria Memory Steward Contract",
            ContextRetrievalIntent.EXACT_OR_TITLE,
            RagStrategy.FTS_ONLY,
            False,
            (),
        ),
        (
            "현재 Rust compute migration 최종 상태가 뭐야?",
            ContextRetrievalIntent.TEMPORAL_CURRENT_STATE,
            RagStrategy.HYBRID,
            False,
            (),
        ),
        (
            "전에 비슷한 장애가 있었나?",
            ContextRetrievalIntent.EXPERIENTIAL,
            RagStrategy.HYBRID,
            False,
            (MemoryFunction.EXPERIENTIAL,),
        ),
        (
            "이 작업은 어떤 순서로 진행해야 하나?",
            ContextRetrievalIntent.PROCEDURAL,
            RagStrategy.HYBRID,
            False,
            (MemoryFunction.PROCEDURAL,),
        ),
        (
            "이 기억은 무엇과 관련되어 있고 어떤 관계가 있나?",
            ContextRetrievalIntent.GRAPH_ORIENTED,
            RagStrategy.HYBRID,
            True,
            (),
        ),
        (
            "왜 retrieval quality가 떨어졌는지 설명해줘?",
            ContextRetrievalIntent.SEMANTIC_PARAPHRASE,
            RagStrategy.HYBRID,
            False,
            (),
        ),
        (
            "retrieval quality regression evidence",
            ContextRetrievalIntent.EXACT_OR_TITLE,
            RagStrategy.FTS_ONLY,
            False,
            (),
        ),
    ],
)
def test_adaptive_planner_classifies_queries_deterministically(
    query: str,
    intent: ContextRetrievalIntent,
    strategy: RagStrategy,
    graph_enabled: bool,
    preferred: tuple[MemoryFunction, ...],
) -> None:
    """Planner v1 should emit stable typed plans for representative query classes."""
    first = build_context_retrieval_plan(query, 5)
    second = build_context_retrieval_plan(query, 5)

    assert first == second
    assert first.profile_version == ADAPTIVE_RETRIEVAL_PROFILE_VERSION
    assert first.intent is intent
    assert first.strategy is strategy
    assert first.graph_enabled is graph_enabled
    assert first.graph_depth == (2 if graph_enabled else 0)
    assert first.preferred_memory_functions == preferred
    assert first.top_k == 5
    assert first.strategy is not RagStrategy.AUTO
    if strategy is RagStrategy.FTS_ONLY:
        assert first.fts_budget == 5
        assert first.vector_budget == 0
        assert first.candidate_multiplier == 1
        assert first.fusion_profile is ContextRetrievalFusionProfile.NONE
    else:
        assert first.fts_budget == 30
        assert first.vector_budget == 30
        assert first.candidate_multiplier == 6
        assert first.fusion_profile is ContextRetrievalFusionProfile.RECIPROCAL_RANK_V1


def test_temporal_plan_marks_current_preference_without_claiming_a_ranking_boost() -> (
    None
):
    """Temporal intent is explicit plan metadata while v1 keeps the proven Hybrid lane."""
    plan = build_context_retrieval_plan("지금 최종 상태는 무엇인가?", 3)

    assert plan.intent is ContextRetrievalIntent.TEMPORAL_CURRENT_STATE
    assert plan.strategy is RagStrategy.HYBRID
    assert plan.temporal_current_preference is True
    assert "temporal_marker" in plan.reasons


def test_temporal_graph_query_preserves_temporal_intent_and_enables_graph_expansion() -> (
    None
):
    """Explicit graph requests compose with temporal preference instead of disabling graph recall."""
    plan = build_context_retrieval_plan(
        "retrieval benchmark harness와 최종 performance verification 관계를 graph로 확인",
        5,
    )

    assert plan.intent is ContextRetrievalIntent.TEMPORAL_CURRENT_STATE
    assert plan.strategy is RagStrategy.HYBRID
    assert plan.temporal_current_preference is True
    assert plan.graph_enabled is True
    assert plan.graph_depth == 2


def test_explicit_memory_function_preference_overrides_planner_inference() -> None:
    """Caller-provided functional-memory priorities must outrank heuristic inference."""
    plan = build_context_retrieval_plan(
        "전에 비슷한 장애가 있었나?",
        5,
        caller_memory_functions=(MemoryFunction.PROCEDURAL, MemoryFunction.FACTUAL),
    )

    assert plan.intent is ContextRetrievalIntent.EXPERIENTIAL
    assert plan.preferred_memory_functions == (
        MemoryFunction.PROCEDURAL,
        MemoryFunction.FACTUAL,
    )


def test_adaptive_plan_caps_hybrid_candidate_budget() -> None:
    """Planner budgets must stay within the frozen retrieval-kernel bound."""
    plan = build_context_retrieval_plan("왜 이 결과가 달라졌는지 설명해줘?", 50)

    assert plan.strategy is RagStrategy.HYBRID
    assert plan.fts_budget == 50
    assert plan.vector_budget == 50


def test_rag_strategy_fixed_excludes_auto() -> None:
    """Existing fixed-lane benchmark semantics must remain explicit after AUTO addition."""
    assert RagStrategy.fixed() == (
        RagStrategy.FTS_ONLY,
        RagStrategy.VECTOR_ONLY,
        RagStrategy.HYBRID,
    )


def test_plan_rejects_auto_as_an_execution_lane() -> None:
    """AUTO is a request mode and must never cross into direct lane execution."""
    with pytest.raises(ValueError, match="fixed retrieval lane"):
        ContextRetrievalPlan(
            profile_version=ADAPTIVE_RETRIEVAL_PROFILE_VERSION,
            intent=ContextRetrievalIntent.MIXED,
            strategy=RagStrategy.AUTO,
            lexical_enabled=True,
            vector_enabled=True,
            graph_enabled=False,
            fts_budget=5,
            vector_budget=5,
            graph_depth=0,
            candidate_multiplier=1,
            fusion_profile=ContextRetrievalFusionProfile.RECIPROCAL_RANK_V1,
            top_k=5,
            preferred_memory_functions=(),
            temporal_current_preference=False,
            reasons=("invalid-test",),
        )
