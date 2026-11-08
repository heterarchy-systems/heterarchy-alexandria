"""Freeze high-level recall results after route orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.application.retrieval.context_pack import build_context_pack
from app.memory.application.retrieval.context_retrieval_metadata import (
    canonical_context_id,
)
from app.memory.application.retrieval.recall.recall_policy import RecallMatchPolicy
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.entities.recall import (
    RecallMatch,
    RecallProvenance,
    RecallResult,
    RecallStageTrace,
    RecallTrace,
)
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)


def with_provenance(
    match: ContextSearchMatch,
    route: RecallRoute,
    affinity: RecallProjectAffinity,
    exact_contribution: str | None,
    temporal_eligible: bool | None,
) -> RecallMatch:
    """Build one bounded provenance wrapper from existing search evidence.

    Args:
        match: Underlying Context search match.
        route: Recall stage route that produced the match.
        affinity: Project affinity classification for the stage.
        exact_contribution: Optional exact-selector kind that matched.
        temporal_eligible: Whether the match satisfied temporal eligibility.

    Returns:
        Recall match paired with bounded provenance metadata.
    """
    return RecallMatch(
        match=match,
        provenance=RecallProvenance(
            route=route,
            project_affinity=affinity,
            canonical_context_id=canonical_context_id(match.context),
            authority=RecallMatchPolicy.memory_authority(match),
            chunk_id=match.chunk.id,
            heading=match.chunk.heading,
            project=match.context.project,
            fts_score=match.fts_score,
            vector_score=match.vector_score,
            graph_score=match.graph_score,
            confidence=RecallMatchPolicy.match_confidence(
                match, exact=route is RecallRoute.EXACT_SELECTOR
            ),
            exact_contribution=exact_contribution,
            source_revision=RecallMatchPolicy.metadata_text(
                match=match, key="source_revision"
            ),
            index_revision=RecallMatchPolicy.metadata_text(
                match=match, key="index_revision"
            ),
            lifecycle_eligible=RecallMatchPolicy.lifecycle_eligible(match),
            temporal_eligible=temporal_eligible,
            title_alias_contribution=(
                "ALIAS" if "declared Obsidian alias" in match.why_retrieved else None
            ),
        ),
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
    """Deduplicate matches and freeze the bounded result contract.

    Args:
        request: Validated recall request.
        scope_mode: Effective scope resolution mode.
        recall_scopes: Resolved scopes included in recall.
        stages: Ordered stage execution traces.
        skipped_scopes: Scope markers skipped during resolution.
        raw_matches: Candidate matches collected across stages.
        warnings: Diagnostic warnings collected across stages.
        degraded_subsystems: Degraded subsystem identifiers.
        effective_strategy: Effective RAG strategy for the recall cascade.
        fallback_routes: Fallback routes attempted during recall.

    Returns:
        Frozen high-level recall result entity.
    """
    deduped = RecallMatchPolicy.deduplicate_matches(
        matches=raw_matches, limit=request.limit
    )
    confident = RecallMatchPolicy.has_confident(deduped)
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
            query=request.query,
            matches=[item.match for item in deduped],
        ),
        trace=trace,
    )
