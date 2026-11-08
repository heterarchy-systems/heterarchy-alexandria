"""Bounded agent-facing recall orchestration over existing retrieval authorities."""

from __future__ import annotations

from app.memory.application.contexts.records.context_service import (
    ContextService,
)
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.recall.recall_historical import (
    HistoricalRecallCascade,
)
from app.memory.application.retrieval.recall.recall_policy import (
    RecallMatchPolicy,
    RecallScopePolicy,
    RecallStagePolicy,
)
from app.memory.application.retrieval.recall.recall_result import (
    build_recall_result,
    with_provenance,
)
from app.memory.application.retrieval.recall.recall_stages import (
    RecallStageExecutor,
)
from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelectorResolver,
    RecallRequest,
)
from app.memory.domain.entities.recall import (
    RecallMatch,
    RecallResult,
    RecallStageTrace,
)
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import (
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)


class RecallService:
    """Resolve scopes and execute one observable, bounded recall cascade."""

    def __init__(
        self,
        context_service: ContextService,
        temporal_recall_service: MemoryTemporalRecallService,
        exact_selector_resolver: RecallExactSelectorResolver,
    ) -> None:
        """Create a high-level recall service from existing authorities.

        Args:
            context_service: Existing FTS/vector/hybrid Context search authority.
            temporal_recall_service: Existing temporal overlay authority.
            exact_selector_resolver: Canonical source-read adapter for exact selectors.
        """
        self._stage_executor = RecallStageExecutor(
            context_service=context_service,
            temporal_recall_service=temporal_recall_service,
            exact_selector_resolver=exact_selector_resolver,
        )
        self._historical_cascade = HistoricalRecallCascade(
            temporal_recall_service=temporal_recall_service
        )

    async def recall(self, request: RecallRequest) -> RecallResult:
        """Recall current or historical memory through a bounded cascade.

        Args:
            request: Typed high-level recall request.

        Returns:
            Recall result with matches, route trace, and bounded provenance.

        Raises:
            MemoryContextValidationError: When request or strict scope identity is
                invalid. Validation errors are never converted into degradation.
        """
        normalized = RecallScopePolicy.validated_request(request)
        scope_identity, recall_scopes, skipped_scopes = (
            RecallScopePolicy.resolve_scope_identity(normalized)
        )
        if normalized.as_of is not None:
            return await self._historical_cascade.recall(
                request=normalized,
                recall_scopes=recall_scopes,
                skipped_scopes=skipped_scopes,
            )

        stage_traces = [
            RecallStageTrace(
                route=RecallRoute.EXACT_SELECTOR,
                status=RecallStageStatus.SKIPPED,
                hit_count=0,
                project=None,
                effective_strategy=None,
                reason=(
                    "selector_not_requested"
                    if normalized.selector is None
                    else "exact_selector_pending"
                ),
            )
        ]
        warnings: list[str] = list(skipped_scopes)
        degraded_subsystems: list[str] = []
        if normalized.selector is not None:
            exact_output = await self._stage_executor.resolve_exact(
                request=normalized,
                scope_identity=scope_identity,
            )
            stage_traces[-1] = exact_output.trace
            if exact_output.trace.degraded:
                degraded_subsystems.append("exact_source")
                warnings.extend(exact_output.trace.warnings)
            if exact_output.matches:
                return build_recall_result(
                    normalized,
                    scope_mode=normalized.scope_mode,
                    recall_scopes=recall_scopes,
                    stages=stage_traces,
                    raw_matches=[
                        with_provenance(
                            match,
                            route=RecallRoute.EXACT_SELECTOR,
                            affinity=(
                                RecallProjectAffinity.PRIMARY
                                if normalized.project is not None
                                else RecallProjectAffinity.GLOBAL
                            ),
                            exact_contribution=RecallScopePolicy.selector_kind(
                                normalized
                            ),
                            temporal_eligible=exact_output.temporal_eligible,
                        )
                        for match in exact_output.matches
                    ],
                    warnings=warnings,
                    degraded_subsystems=degraded_subsystems,
                    effective_strategy=RagStrategy.AUTO,
                    skipped_scopes=skipped_scopes,
                )

        raw_matches: list[RecallMatch] = []
        effective_strategies: list[RagStrategy] = []
        primary_project = normalized.project
        primary_scopes = RecallScopePolicy.route_scopes(
            request=normalized,
            resolved_scopes=recall_scopes,
            project=primary_project,
        )
        primary_affinity = (
            RecallProjectAffinity.PRIMARY
            if ContextScope.PROJECT in primary_scopes
            else RecallProjectAffinity.GLOBAL
        )
        primary_fts = await self._stage_executor.run_stage(
            route=RecallRoute.PRIMARY_FTS,
            query=normalized.query,
            project=primary_project,
            scopes=primary_scopes,
            request=normalized,
            strategy=RagStrategy.FTS_ONLY,
        )
        stage_traces.append(primary_fts.trace)
        raw_matches.extend(
            with_provenance(
                match,
                route=RecallRoute.PRIMARY_FTS,
                affinity=primary_affinity,
                exact_contribution=None,
                temporal_eligible=primary_fts.temporal_eligible,
            )
            for match in primary_fts.matches
        )
        RecallStagePolicy.record_stage_state(
            trace=primary_fts.trace,
            warnings=warnings,
            degraded_subsystems=degraded_subsystems,
        )
        if primary_fts.trace.effective_strategy is not None:
            effective_strategies.append(primary_fts.trace.effective_strategy)

        if not RecallMatchPolicy.has_confident(raw_matches):
            primary_semantic = await self._stage_executor.run_stage(
                route=RecallRoute.PRIMARY_SEMANTIC,
                query=normalized.query,
                project=primary_project,
                scopes=primary_scopes,
                request=normalized,
                strategy=(
                    RagStrategy.VECTOR_ONLY
                    if not primary_fts.matches
                    else RagStrategy.HYBRID
                ),
            )
            stage_traces.append(primary_semantic.trace)
            raw_matches.extend(
                with_provenance(
                    match,
                    route=RecallRoute.PRIMARY_SEMANTIC,
                    affinity=primary_affinity,
                    exact_contribution=None,
                    temporal_eligible=primary_semantic.temporal_eligible,
                )
                for match in primary_semantic.matches
            )
            RecallStagePolicy.record_stage_state(
                trace=primary_semantic.trace,
                warnings=warnings,
                degraded_subsystems=degraded_subsystems,
            )
            if primary_semantic.trace.effective_strategy is not None:
                effective_strategies.append(primary_semantic.trace.effective_strategy)

        related_projects = normalized.related_projects
        if (
            normalized.scope_mode is RecallScopeMode.STRICT
            and ContextScope.PROJECT not in recall_scopes
        ):
            related_projects = ()
        if not RecallMatchPolicy.has_confident(raw_matches):
            for project in related_projects:
                related_fts = await self._stage_executor.run_stage(
                    route=RecallRoute.RELATED_PROJECT_FTS,
                    query=normalized.query,
                    project=project,
                    scopes=RecallScopePolicy.route_scopes(
                        request=normalized,
                        resolved_scopes=recall_scopes,
                        project=project,
                    ),
                    request=normalized,
                    strategy=RagStrategy.FTS_ONLY,
                )
                stage_traces.append(related_fts.trace)
                raw_matches.extend(
                    with_provenance(
                        match,
                        route=RecallRoute.RELATED_PROJECT_FTS,
                        affinity=RecallProjectAffinity.RELATED,
                        exact_contribution=None,
                        temporal_eligible=related_fts.temporal_eligible,
                    )
                    for match in related_fts.matches
                )
                RecallStagePolicy.record_stage_state(
                    trace=related_fts.trace,
                    warnings=warnings,
                    degraded_subsystems=degraded_subsystems,
                )
                if related_fts.trace.effective_strategy is not None:
                    effective_strategies.append(related_fts.trace.effective_strategy)
                if RecallMatchPolicy.has_confident(raw_matches):
                    break
                related_semantic = await self._stage_executor.run_stage(
                    route=RecallRoute.RELATED_PROJECT_SEMANTIC,
                    query=normalized.query,
                    project=project,
                    scopes=RecallScopePolicy.route_scopes(
                        request=normalized,
                        resolved_scopes=recall_scopes,
                        project=project,
                    ),
                    request=normalized,
                    strategy=(
                        RagStrategy.VECTOR_ONLY
                        if not related_fts.matches
                        else RagStrategy.HYBRID
                    ),
                )
                stage_traces.append(related_semantic.trace)
                raw_matches.extend(
                    with_provenance(
                        match,
                        route=RecallRoute.RELATED_PROJECT_SEMANTIC,
                        affinity=RecallProjectAffinity.RELATED,
                        exact_contribution=None,
                        temporal_eligible=related_semantic.temporal_eligible,
                    )
                    for match in related_semantic.matches
                )
                RecallStagePolicy.record_stage_state(
                    trace=related_semantic.trace,
                    warnings=warnings,
                    degraded_subsystems=degraded_subsystems,
                )
                if related_semantic.trace.effective_strategy is not None:
                    effective_strategies.append(
                        related_semantic.trace.effective_strategy
                    )
                if RecallMatchPolicy.has_confident(raw_matches):
                    break

        if not RecallMatchPolicy.has_confident(raw_matches) and (
            normalized.scope_mode is RecallScopeMode.AUTO
            or ContextScope.GLOBAL in recall_scopes
        ):
            global_scopes = (ContextScope.GLOBAL,)
            global_fts = await self._stage_executor.run_stage(
                route=RecallRoute.GLOBAL_FTS,
                query=normalized.query,
                project=None,
                scopes=global_scopes,
                request=normalized,
                strategy=RagStrategy.FTS_ONLY,
            )
            stage_traces.append(global_fts.trace)
            raw_matches.extend(
                with_provenance(
                    match,
                    route=RecallRoute.GLOBAL_FTS,
                    affinity=RecallProjectAffinity.GLOBAL,
                    exact_contribution=None,
                    temporal_eligible=global_fts.temporal_eligible,
                )
                for match in global_fts.matches
            )
            RecallStagePolicy.record_stage_state(
                trace=global_fts.trace,
                warnings=warnings,
                degraded_subsystems=degraded_subsystems,
            )
            if global_fts.trace.effective_strategy is not None:
                effective_strategies.append(global_fts.trace.effective_strategy)
            if not RecallMatchPolicy.has_confident(raw_matches):
                global_semantic = await self._stage_executor.run_stage(
                    route=RecallRoute.GLOBAL_SEMANTIC,
                    query=normalized.query,
                    project=None,
                    scopes=global_scopes,
                    request=normalized,
                    strategy=(
                        RagStrategy.VECTOR_ONLY
                        if not global_fts.matches
                        else RagStrategy.HYBRID
                    ),
                )
                stage_traces.append(global_semantic.trace)
                raw_matches.extend(
                    with_provenance(
                        match,
                        route=RecallRoute.GLOBAL_SEMANTIC,
                        affinity=RecallProjectAffinity.GLOBAL,
                        exact_contribution=None,
                        temporal_eligible=global_semantic.temporal_eligible,
                    )
                    for match in global_semantic.matches
                )
                RecallStagePolicy.record_stage_state(
                    trace=global_semantic.trace,
                    warnings=warnings,
                    degraded_subsystems=degraded_subsystems,
                )
                if global_semantic.trace.effective_strategy is not None:
                    effective_strategies.append(
                        global_semantic.trace.effective_strategy
                    )

        fallback_routes = tuple(
            stage.route
            for stage in stage_traces
            if stage.status is RecallStageStatus.ATTEMPTED
            and stage.route
            in {
                RecallRoute.RELATED_PROJECT_FTS,
                RecallRoute.RELATED_PROJECT_SEMANTIC,
                RecallRoute.GLOBAL_FTS,
                RecallRoute.GLOBAL_SEMANTIC,
            }
        )
        return build_recall_result(
            normalized,
            scope_mode=normalized.scope_mode,
            recall_scopes=recall_scopes,
            stages=stage_traces,
            raw_matches=raw_matches,
            warnings=warnings,
            degraded_subsystems=degraded_subsystems,
            effective_strategy=(
                effective_strategies[-1] if effective_strategies else RagStrategy.AUTO
            ),
            skipped_scopes=skipped_scopes,
            fallback_routes=fallback_routes,
        )
