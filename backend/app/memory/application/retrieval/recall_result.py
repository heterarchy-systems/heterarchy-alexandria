"""Freeze high-level recall results after route orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.application.retrieval.context_pack import build_context_pack
from app.memory.application.retrieval.recall_policy import deduplicate_matches
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.recall import (
    RecallMatch,
    RecallResult,
    RecallStageTrace,
    RecallTrace,
)
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)


def build_recall_result(
    request: RecallRequest,
    *,
    scope_mode: RecallScopeMode,
    recall_scopes: tuple[ContextScope, ...],
    stages: Sequence[RecallStageTrace],
    skipped_scopes: Sequence[str],
    raw_matches: Sequence[RecallMatch],
    warnings: Sequence[str],
    degraded_subsystems: Sequence[str],
    effective_strategy: RagStrategy,
    fallback_routes: tuple[RecallRoute, ...] = (),
) -> RecallResult:
    """Deduplicate matches and freeze the bounded result contract."""
    deduped = deduplicate_matches(raw_matches, request.limit)
    confident = any(item.provenance.confidence >= 0.5 for item in deduped)
    if confident:
        outcome = RecallOutcome.MATCHED
    elif degraded_subsystems:
        outcome = RecallOutcome.DEGRADED_SEARCH
    elif deduped:
        outcome = RecallOutcome.NO_CONFIDENT_MATCH
    else:
        outcome = RecallOutcome.SEARCH_EXHAUSTED
    all_warnings = tuple(dict.fromkeys(item for item in warnings if item))
    trace = RecallTrace(
        stages=tuple(stages),
        skipped_scopes=tuple(dict.fromkeys(skipped_scopes)),
        fallback_expansion=fallback_routes,
        degraded_subsystems=tuple(dict.fromkeys(degraded_subsystems)),
        outcome=outcome,
        confidence=max(
            (item.provenance.confidence for item in deduped),
            default=0.0,
        ),
        search_call_count=sum(
            1
            for stage in stages
            if stage.status is RecallStageStatus.ATTEMPTED
            and stage.route is not RecallRoute.EXACT_SELECTOR
        ),
    )
    return RecallResult(
        query=request.query,
        scope_mode=scope_mode,
        recall_scopes=recall_scopes,
        effective_strategy=effective_strategy,
        outcome=outcome,
        warnings=all_warnings,
        matches=tuple(deduped),
        context_pack=build_context_pack(
            request.query,
            [item.match for item in deduped],
        ),
        trace=trace,
    )
