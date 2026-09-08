"""Bounded agent-facing recall orchestration over existing retrieval authorities."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from app.memory.application.contexts.records.context_service import (
    ContextService,
)
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.context_retrieval_metadata import (
    canonical_context_id,
)
from app.memory.application.retrieval.planning.context_scope_filter import (
    filter_context_matches,
)
from app.memory.application.retrieval.recall_policy import (
    exception_name as _exception_name,
    has_confident as _has_confident,
    historical_lifecycle_statuses as _historical_lifecycle_statuses,
    lifecycle_eligible as _lifecycle_eligible,
    match_confidence as _match_confidence,
    memory_authority as _memory_authority,
    metadata_text as _metadata_text,
    pack_is_degraded as _pack_is_degraded,
    record_stage_state as _record_stage_state,
    resolve_scope_identity as _resolve_scope_identity,
    route_scopes as _route_scopes,
    selector_kind as _selector_kind,
    validated_request as _validated_request,
)
from app.memory.application.retrieval.recall_result import build_recall_result
from app.memory.domain.contracts.context_recall_contracts import ScopeIdentity
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelectorResolver,
    RecallRequest,
)
from app.memory.domain.entities.context_read_models import (
    ContextPack,
    ContextSearchMatch,
)
from app.memory.domain.entities.recall import (
    RecallMatch,
    RecallProvenance,
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
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class _StageOutput:
    """Internal output from one bounded retrieval stage."""

    matches: tuple[ContextSearchMatch, ...]
    trace: RecallStageTrace
    temporal_eligible: bool | None = None


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
        self._context_service = context_service
        self._temporal_recall_service = temporal_recall_service
        self._exact_selector_resolver = exact_selector_resolver

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
        normalized = _validated_request(request)
        scope_identity, recall_scopes, skipped_scopes = _resolve_scope_identity(
            normalized
        )
        if normalized.as_of is not None:
            return await self._recall_historical(
                normalized,
                scope_identity=scope_identity,
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
            exact_output = await self._resolve_exact(
                normalized,
                scope_identity=scope_identity,
            )
            stage_traces[-1] = exact_output.trace
            if exact_output.trace.degraded:
                degraded_subsystems.append("exact_source")
                warnings.extend(exact_output.trace.warnings)
            if exact_output.matches:
                return self._build_result(
                    normalized,
                    scope_mode=normalized.scope_mode,
                    recall_scopes=recall_scopes,
                    stages=stage_traces,
                    raw_matches=[
                        self._with_provenance(
                            match,
                            route=RecallRoute.EXACT_SELECTOR,
                            affinity=(
                                RecallProjectAffinity.PRIMARY
                                if normalized.project is not None
                                else RecallProjectAffinity.GLOBAL
                            ),
                            exact_contribution=_selector_kind(normalized),
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
        primary_scopes = _route_scopes(
            normalized,
            recall_scopes,
            project=primary_project,
        )
        primary_affinity = (
            RecallProjectAffinity.PRIMARY
            if ContextScope.PROJECT in primary_scopes
            else RecallProjectAffinity.GLOBAL
        )
        primary_fts = await self._run_stage(
            route=RecallRoute.PRIMARY_FTS,
            query=normalized.query,
            project=primary_project,
            scopes=primary_scopes,
            request=normalized,
            strategy=RagStrategy.FTS_ONLY,
        )
        stage_traces.append(primary_fts.trace)
        raw_matches.extend(
            self._with_provenance(
                match,
                route=RecallRoute.PRIMARY_FTS,
                affinity=primary_affinity,
                exact_contribution=None,
                temporal_eligible=primary_fts.temporal_eligible,
            )
            for match in primary_fts.matches
        )
        _record_stage_state(primary_fts.trace, warnings, degraded_subsystems)
        if primary_fts.trace.effective_strategy is not None:
            effective_strategies.append(primary_fts.trace.effective_strategy)

        if not _has_confident(raw_matches):
            primary_semantic = await self._run_stage(
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
                self._with_provenance(
                    match,
                    route=RecallRoute.PRIMARY_SEMANTIC,
                    affinity=primary_affinity,
                    exact_contribution=None,
                    temporal_eligible=primary_semantic.temporal_eligible,
                )
                for match in primary_semantic.matches
            )
            _record_stage_state(primary_semantic.trace, warnings, degraded_subsystems)
            if primary_semantic.trace.effective_strategy is not None:
                effective_strategies.append(primary_semantic.trace.effective_strategy)

        related_projects = normalized.related_projects
        if (
            normalized.scope_mode is RecallScopeMode.STRICT
            and ContextScope.PROJECT not in recall_scopes
        ):
            related_projects = ()
        if not _has_confident(raw_matches):
            for project in related_projects:
                related_fts = await self._run_stage(
                    route=RecallRoute.RELATED_PROJECT_FTS,
                    query=normalized.query,
                    project=project,
                    scopes=_route_scopes(normalized, recall_scopes, project=project),
                    request=normalized,
                    strategy=RagStrategy.FTS_ONLY,
                )
                stage_traces.append(related_fts.trace)
                raw_matches.extend(
                    self._with_provenance(
                        match,
                        route=RecallRoute.RELATED_PROJECT_FTS,
                        affinity=RecallProjectAffinity.RELATED,
                        exact_contribution=None,
                        temporal_eligible=related_fts.temporal_eligible,
                    )
                    for match in related_fts.matches
                )
                _record_stage_state(related_fts.trace, warnings, degraded_subsystems)
                if related_fts.trace.effective_strategy is not None:
                    effective_strategies.append(related_fts.trace.effective_strategy)
                if _has_confident(raw_matches):
                    break
                related_semantic = await self._run_stage(
                    route=RecallRoute.RELATED_PROJECT_SEMANTIC,
                    query=normalized.query,
                    project=project,
                    scopes=_route_scopes(normalized, recall_scopes, project=project),
                    request=normalized,
                    strategy=(
                        RagStrategy.VECTOR_ONLY
                        if not related_fts.matches
                        else RagStrategy.HYBRID
                    ),
                )
                stage_traces.append(related_semantic.trace)
                raw_matches.extend(
                    self._with_provenance(
                        match,
                        route=RecallRoute.RELATED_PROJECT_SEMANTIC,
                        affinity=RecallProjectAffinity.RELATED,
                        exact_contribution=None,
                        temporal_eligible=related_semantic.temporal_eligible,
                    )
                    for match in related_semantic.matches
                )
                _record_stage_state(
                    related_semantic.trace,
                    warnings,
                    degraded_subsystems,
                )
                if related_semantic.trace.effective_strategy is not None:
                    effective_strategies.append(
                        related_semantic.trace.effective_strategy
                    )
                if _has_confident(raw_matches):
                    break

        if not _has_confident(raw_matches) and (
            normalized.scope_mode is RecallScopeMode.AUTO
            or ContextScope.GLOBAL in recall_scopes
        ):
            global_scopes = (ContextScope.GLOBAL,)
            global_fts = await self._run_stage(
                route=RecallRoute.GLOBAL_FTS,
                query=normalized.query,
                project=None,
                scopes=global_scopes,
                request=normalized,
                strategy=RagStrategy.FTS_ONLY,
            )
            stage_traces.append(global_fts.trace)
            raw_matches.extend(
                self._with_provenance(
                    match,
                    route=RecallRoute.GLOBAL_FTS,
                    affinity=RecallProjectAffinity.GLOBAL,
                    exact_contribution=None,
                    temporal_eligible=global_fts.temporal_eligible,
                )
                for match in global_fts.matches
            )
            _record_stage_state(global_fts.trace, warnings, degraded_subsystems)
            if global_fts.trace.effective_strategy is not None:
                effective_strategies.append(global_fts.trace.effective_strategy)
            if not _has_confident(raw_matches):
                global_semantic = await self._run_stage(
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
                    self._with_provenance(
                        match,
                        route=RecallRoute.GLOBAL_SEMANTIC,
                        affinity=RecallProjectAffinity.GLOBAL,
                        exact_contribution=None,
                        temporal_eligible=global_semantic.temporal_eligible,
                    )
                    for match in global_semantic.matches
                )
                _record_stage_state(
                    global_semantic.trace,
                    warnings,
                    degraded_subsystems,
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
        return self._build_result(
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

    async def _resolve_exact(
        self,
        request: RecallRequest,
        *,
        scope_identity: ScopeIdentity,
    ) -> _StageOutput:
        """Resolve one exact selector through the optional canonical source port."""
        if request.selector is None:
            return _StageOutput(
                matches=(),
                trace=RecallStageTrace(
                    route=RecallRoute.EXACT_SELECTOR,
                    status=RecallStageStatus.SKIPPED,
                    hit_count=0,
                    project=None,
                    effective_strategy=None,
                    reason="selector_not_requested",
                ),
            )
        try:
            matches = await self._exact_selector_resolver.resolve(
                request.selector,
                scope_identity,
            )
        except MemoryContextValidationError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _StageOutput(
                matches=(),
                trace=RecallStageTrace(
                    route=RecallRoute.EXACT_SELECTOR,
                    status=RecallStageStatus.FAILED,
                    hit_count=0,
                    project=request.project,
                    effective_strategy=None,
                    reason="exact_selector_failed",
                    warnings=(
                        "Exact selector unavailable "
                        f"[{_exception_name(exc)}]; retrieval cascade continued.",
                    ),
                    degraded=True,
                ),
            )
        filtered = filter_context_matches(list(matches), scope_identity)
        if not filtered:
            return _StageOutput(
                matches=(),
                trace=RecallStageTrace(
                    route=RecallRoute.EXACT_SELECTOR,
                    status=RecallStageStatus.ATTEMPTED,
                    hit_count=0,
                    project=request.project,
                    effective_strategy=None,
                    reason="exact_selector_not_found",
                ),
            )
        source_pack = ContextPack(
            query=request.query,
            strategy=RagStrategy.AUTO,
            effective_strategy=RagStrategy.AUTO,
            warnings=(),
            recall_scopes=scope_identity.include_scopes,
            matches=tuple(filtered),
            context_pack="",
        )
        try:
            temporal_view = await self._temporal_recall_service.apply_view(
                source_pack,
                MemoryTemporalRecallRequest(
                    query=request.query,
                    mode=MemoryTemporalRecallMode.CURRENT,
                    strategy=RagStrategy.AUTO,
                    limit=request.limit,
                    project=request.project,
                    kind=request.kind,
                    include_scopes=scope_identity.include_scopes,
                    workspace_id=request.workspace_id,
                    agent_id=request.agent_id,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    include_lifecycle_statuses=request.include_lifecycle_statuses,
                ),
            )
        except MemoryContextValidationError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _StageOutput(
                matches=tuple(filtered),
                trace=RecallStageTrace(
                    route=RecallRoute.EXACT_SELECTOR,
                    status=RecallStageStatus.ATTEMPTED,
                    hit_count=len(filtered),
                    project=request.project,
                    effective_strategy=None,
                    reason="exact_match_temporal_projection_unavailable",
                    warnings=(
                        "Exact canonical source read preserved; temporal projection "
                        f"unavailable [{_exception_name(exc)}].",
                    ),
                    degraded=True,
                ),
            )
        viewed_matches = tuple(item.match for item in temporal_view.matches)
        return _StageOutput(
            matches=viewed_matches,
            trace=RecallStageTrace(
                route=RecallRoute.EXACT_SELECTOR,
                status=RecallStageStatus.ATTEMPTED,
                hit_count=len(viewed_matches),
                project=request.project,
                effective_strategy=None,
                reason=(
                    "exact_match" if viewed_matches else "exact_selector_not_current"
                ),
                warnings=tuple(temporal_view.warnings),
            ),
            temporal_eligible=True,
        )

    async def _run_stage(
        self,
        *,
        route: RecallRoute,
        query: str,
        project: str | None,
        scopes: tuple[ContextScope, ...],
        request: RecallRequest,
        strategy: RagStrategy,
    ) -> _StageOutput:
        """Run an existing Context search lane and classify degradation."""
        try:
            result = await self._context_service.explain_search(
                query=query,
                strategy=strategy,
                limit=request.limit,
                project=project,
                kind=request.kind,
                include_scopes=list(scopes),
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                user_id=request.user_id,
                session_id=request.session_id,
                include_lifecycle_statuses=list(request.include_lifecycle_statuses)
                or None,
            )
            temporal_view = await self._temporal_recall_service.apply_view(
                result.pack,
                MemoryTemporalRecallRequest(
                    query=query,
                    mode=MemoryTemporalRecallMode.CURRENT,
                    strategy=strategy,
                    limit=request.limit,
                    project=project,
                    kind=request.kind,
                    include_scopes=scopes,
                    workspace_id=request.workspace_id,
                    agent_id=request.agent_id,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    include_lifecycle_statuses=request.include_lifecycle_statuses,
                ),
            )
        except MemoryContextValidationError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _StageOutput(
                matches=(),
                trace=RecallStageTrace(
                    route=route,
                    status=RecallStageStatus.FAILED,
                    hit_count=0,
                    project=project,
                    effective_strategy=None,
                    reason="retrieval_stage_failed",
                    warnings=(
                        f"{route.value} unavailable [{_exception_name(exc)}]; "
                        "bounded fallback continued.",
                    ),
                    degraded=True,
                ),
            )
        degraded = _pack_is_degraded(
            temporal_view.warnings, result.pack.effective_strategy, strategy
        )
        return _StageOutput(
            matches=tuple(item.match for item in temporal_view.matches),
            trace=RecallStageTrace(
                route=route,
                status=RecallStageStatus.ATTEMPTED,
                hit_count=len(temporal_view.matches),
                project=project,
                effective_strategy=result.pack.effective_strategy,
                reason=("matches" if temporal_view.matches else "no_matches"),
                warnings=tuple(temporal_view.warnings),
                degraded=degraded,
            ),
            temporal_eligible=True,
        )

    async def _recall_historical(
        self,
        request: RecallRequest,
        *,
        scope_identity: ScopeIdentity,
        recall_scopes: tuple[ContextScope, ...],
        skipped_scopes: tuple[str, ...],
    ) -> RecallResult:
        """Use the existing temporal service for every historical stage."""
        del scope_identity
        stage_traces = [
            RecallStageTrace(
                route=RecallRoute.EXACT_SELECTOR,
                status=RecallStageStatus.SKIPPED,
                hit_count=0,
                project=None,
                effective_strategy=None,
                reason="historical_recall_uses_temporal_authority",
            )
        ]
        raw_matches: list[RecallMatch] = []
        warnings: list[str] = list(skipped_scopes)
        degraded_subsystems: list[str] = []
        projects: list[tuple[str | None, RecallProjectAffinity]] = []
        if request.project is not None:
            projects.append((request.project, RecallProjectAffinity.PRIMARY))
        else:
            projects.append((None, RecallProjectAffinity.PRIMARY))
        projects.extend(
            (project, RecallProjectAffinity.RELATED)
            for project in request.related_projects
        )
        if (
            request.scope_mode is RecallScopeMode.AUTO
            or ContextScope.GLOBAL in recall_scopes
        ):
            projects.append((None, RecallProjectAffinity.GLOBAL))
        seen_project_lanes: set[tuple[str | None, RecallProjectAffinity]] = set()
        effective_strategy = RagStrategy.AUTO
        for project, affinity in projects:
            if (project, affinity) in seen_project_lanes:
                continue
            seen_project_lanes.add((project, affinity))
            scopes = (
                (ContextScope.GLOBAL,)
                if affinity is RecallProjectAffinity.GLOBAL
                else _route_scopes(request, recall_scopes, project=project)
            )
            try:
                pack = await self._temporal_recall_service.recall(
                    MemoryTemporalRecallRequest(
                        query=request.query,
                        mode=MemoryTemporalRecallMode.HISTORICAL,
                        as_of=request.as_of,
                        strategy=RagStrategy.HYBRID,
                        limit=request.limit,
                        project=project,
                        kind=request.kind,
                        include_scopes=scopes,
                        workspace_id=request.workspace_id,
                        agent_id=request.agent_id,
                        user_id=request.user_id,
                        session_id=request.session_id,
                        include_lifecycle_statuses=_historical_lifecycle_statuses(
                            request
                        ),
                    )
                )
            except MemoryContextValidationError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stage_traces.append(
                    RecallStageTrace(
                        route=RecallRoute.TEMPORAL_HISTORICAL,
                        status=RecallStageStatus.FAILED,
                        hit_count=0,
                        project=project,
                        effective_strategy=None,
                        reason="temporal_stage_failed",
                        warnings=(
                            f"Historical temporal lane unavailable "
                            f"[{_exception_name(exc)}].",
                        ),
                        degraded=True,
                    )
                )
                degraded_subsystems.append("temporal_recall")
                continue
            effective_strategy = pack.effective_strategy
            warnings.extend(pack.warnings)
            stage_traces.append(
                RecallStageTrace(
                    route=RecallRoute.TEMPORAL_HISTORICAL,
                    status=RecallStageStatus.ATTEMPTED,
                    hit_count=len(pack.matches),
                    project=project,
                    effective_strategy=pack.effective_strategy,
                    reason=("matches" if pack.matches else "no_matches"),
                    warnings=tuple(pack.warnings),
                    degraded=False,
                )
            )
            raw_matches.extend(
                self._with_provenance(
                    item.match,
                    route=RecallRoute.TEMPORAL_HISTORICAL,
                    affinity=affinity,
                    exact_contribution=None,
                    temporal_eligible=item.is_current
                    if request.as_of is None
                    else True,
                )
                for item in pack.matches
            )
            if _has_confident(raw_matches):
                break

        return self._build_result(
            request,
            scope_mode=request.scope_mode,
            recall_scopes=recall_scopes,
            stages=stage_traces,
            skipped_scopes=skipped_scopes,
            raw_matches=raw_matches,
            warnings=warnings,
            degraded_subsystems=degraded_subsystems,
            effective_strategy=effective_strategy,
            fallback_routes=tuple(
                stage.route
                for stage in stage_traces
                if stage.route is RecallRoute.TEMPORAL_HISTORICAL
                and stage.status is RecallStageStatus.ATTEMPTED
            ),
        )

    def _with_provenance(
        self,
        match: ContextSearchMatch,
        *,
        route: RecallRoute,
        affinity: RecallProjectAffinity,
        exact_contribution: str | None,
        temporal_eligible: bool | None,
    ) -> RecallMatch:
        """Build one bounded provenance wrapper from existing search evidence."""
        return RecallMatch(
            match=match,
            provenance=RecallProvenance(
                route=route,
                project_affinity=affinity,
                canonical_context_id=canonical_context_id(match.context),
                authority=_memory_authority(match),
                chunk_id=match.chunk.id,
                heading=match.chunk.heading,
                project=match.context.project,
                fts_score=match.fts_score,
                vector_score=match.vector_score,
                graph_score=match.graph_score,
                confidence=_match_confidence(
                    match, exact=route is RecallRoute.EXACT_SELECTOR
                ),
                exact_contribution=exact_contribution,
                source_revision=_metadata_text(match, "source_revision"),
                index_revision=_metadata_text(match, "index_revision"),
                lifecycle_eligible=_lifecycle_eligible(match),
                temporal_eligible=temporal_eligible,
                title_alias_contribution=(
                    "ALIAS"
                    if "declared Obsidian alias" in match.why_retrieved
                    else None
                ),
            ),
        )

    def _build_result(
        self,
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
        """Freeze the route output through the dedicated result owner."""
        return build_recall_result(
            request,
            scope_mode=scope_mode,
            recall_scopes=recall_scopes,
            stages=stages,
            skipped_scopes=skipped_scopes,
            raw_matches=raw_matches,
            warnings=warnings,
            degraded_subsystems=degraded_subsystems,
            effective_strategy=effective_strategy,
            fallback_routes=fallback_routes,
        )
