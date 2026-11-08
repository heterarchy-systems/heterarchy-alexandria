"""Historical recall cascade over the existing temporal authority."""

from __future__ import annotations

import asyncio

from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
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
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.contracts.recall_contracts import RecallRequest
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
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError


class HistoricalRecallCascade:
    """Use the temporal recall service for each bounded historical lane."""

    def __init__(self, temporal_recall_service: MemoryTemporalRecallService) -> None:
        """Initialize the existing temporal recall authority.

        Args:
            temporal_recall_service: Temporal recall service dependency.
        """
        self._temporal_recall_service = temporal_recall_service

    async def recall(
        self,
        request: RecallRequest,
        recall_scopes: tuple[ContextScope, ...],
        skipped_scopes: tuple[str, ...],
    ) -> RecallResult:
        """Use the existing temporal service for every historical stage.

        Args:
            request: Validated recall request with `as_of` timestamp.
            recall_scopes: Resolved scope tuple for the request.
            skipped_scopes: Skipped scope markers recorded during scope resolution.

        Returns:
            Bounded historical recall result with stage traces and provenance.

        Raises:
            MemoryContextValidationError: If temporal recall validation fails.
            asyncio.CancelledError: If the async operation is cancelled.
        """
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
                else RecallScopePolicy.route_scopes(
                    request=request,
                    resolved_scopes=recall_scopes,
                    project=project,
                )
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
                        include_lifecycle_statuses=RecallScopePolicy.historical_lifecycle_statuses(
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
                            f"[{RecallStagePolicy.exception_name(exc)}].",
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
                with_provenance(
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
            if RecallMatchPolicy.has_confident(raw_matches):
                break

        return build_recall_result(
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
