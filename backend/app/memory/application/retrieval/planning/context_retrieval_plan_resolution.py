"""Resolve fixed and adaptive Context retrieval execution without performing I/O."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ContextRetrievalPlan,
    build_context_retrieval_plan,
)
from app.memory.domain.event_enum.context_enums import MemoryFunction, RagStrategy


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextRetrievalExecutionSelection:
    """Pure execution selection consumed by the Context search orchestrator."""

    strategy: RagStrategy
    graph_enabled: bool
    temporal_current_preference: bool
    preferred_memory_functions: tuple[MemoryFunction, ...]
    adaptive_plan: ContextRetrievalPlan | None


def resolve_context_retrieval_execution(
    query: str,
    requested_strategy: RagStrategy,
    limit: int,
    preferred_memory_functions: list[MemoryFunction] | None,
) -> ContextRetrievalExecutionSelection:
    """Resolve one request mode into a fixed lane and optional adaptive plan.

    Args:
        query: Validated search query text.
        requested_strategy: Caller-requested fixed lane or AUTO mode.
        limit: Requested final result count.
        preferred_memory_functions: Validated explicit caller preferences.

    Returns:
        Pure fixed execution selection plus an AUTO plan when requested.
    """
    caller_preferences = tuple(preferred_memory_functions or ())
    if requested_strategy is not RagStrategy.AUTO:
        return ContextRetrievalExecutionSelection(
            strategy=requested_strategy,
            graph_enabled=True,
            temporal_current_preference=False,
            preferred_memory_functions=caller_preferences,
            adaptive_plan=None,
        )
    plan = build_context_retrieval_plan(
        query,
        limit,
        caller_memory_functions=caller_preferences,
    )
    return ContextRetrievalExecutionSelection(
        strategy=plan.strategy,
        graph_enabled=plan.graph_enabled,
        temporal_current_preference=plan.temporal_current_preference,
        preferred_memory_functions=plan.preferred_memory_functions,
        adaptive_plan=plan,
    )


def bounded_auto_hybrid_budgets(
    plan: ContextRetrievalPlan | None,
    native_candidate_limit: int,
    final_limit: int,
) -> tuple[int, int]:
    """Bound AUTO lane budgets by the existing Rust candidate-limit authority.

    Args:
        plan: Optional AUTO plan; fixed requests provide no plan.
        native_candidate_limit: Rust-authoritative maximum pre-fusion candidate count.
        final_limit: Requested final top-k.

    Returns:
        FTS and vector candidate budgets.
    """
    if plan is None:
        return native_candidate_limit, native_candidate_limit
    if plan.strategy is not RagStrategy.HYBRID:
        raise ValueError("AUTO hybrid budgets require a HYBRID execution plan")
    fts_budget = min(native_candidate_limit, max(final_limit, plan.fts_budget))
    vector_budget = min(native_candidate_limit, max(final_limit, plan.vector_budget))
    return fts_budget, vector_budget
