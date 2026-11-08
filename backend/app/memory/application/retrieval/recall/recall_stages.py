"""Existing exact and search I/O authorities used by recall cascades."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.planning.context_scope_filter import (
    filter_context_matches,
)
from app.memory.application.retrieval.recall.recall_policy import RecallStagePolicy
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
from app.memory.domain.entities.recall import RecallStageTrace
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.recall_enums import RecallRoute, RecallStageStatus
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class _StageOutput:
    """Internal output from one bounded retrieval stage."""

    matches: tuple[ContextSearchMatch, ...]
    trace: RecallStageTrace
    temporal_eligible: bool | None = None


class RecallStageExecutor:
    """Run exact selectors and existing Context retrieval lanes."""

    def __init__(
        self,
        context_service: ContextService,
        temporal_recall_service: MemoryTemporalRecallService,
        exact_selector_resolver: RecallExactSelectorResolver,
    ) -> None:
        """Initialize the existing retrieval and temporal authorities.

        Args:
            context_service: Context search service dependency.
            temporal_recall_service: Temporal recall projection service dependency.
            exact_selector_resolver: Canonical source-read adapter for exact selectors.
        """
        self._context_service = context_service
        self._temporal_recall_service = temporal_recall_service
        self._exact_selector_resolver = exact_selector_resolver

    async def resolve_exact(
        self,
        request: RecallRequest,
        scope_identity: ScopeIdentity,
    ) -> _StageOutput:
        """Resolve one exact selector through the optional canonical source port.

        Args:
            request: Validated recall request.
            scope_identity: Validated scope identity filter.

        Returns:
            Stage output with resolved exact matches and stage trace.

        Raises:
            MemoryContextValidationError: If exact selector or temporal validation fails.
            asyncio.CancelledError: If the async operation is cancelled.
        """
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
                        f"[{RecallStagePolicy.exception_name(exc)}]; retrieval cascade continued.",
                    ),
                    degraded=True,
                ),
            )
        filtered = filter_context_matches(
            matches=list(matches),
            scope_filter=scope_identity,
        )
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
                        f"unavailable [{RecallStagePolicy.exception_name(exc)}].",
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

    async def run_stage(
        self,
        route: RecallRoute,
        query: str,
        project: str | None,
        scopes: tuple[ContextScope, ...],
        request: RecallRequest,
        strategy: RagStrategy,
    ) -> _StageOutput:
        """Run an existing Context search lane and classify degradation.

        Args:
            route: Recall route stage being executed.
            query: Search query string.
            project: Optional project filter for the stage.
            scopes: Scopes to include in the stage search.
            request: Validated recall request.
            strategy: RAG retrieval strategy to execute.

        Returns:
            Stage output with temporal-projected matches and stage trace.

        Raises:
            MemoryContextValidationError: If search or temporal validation fails.
            asyncio.CancelledError: If the async operation is cancelled.
        """
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
                        f"{route.value} unavailable [{RecallStagePolicy.exception_name(exc)}]; "
                        "bounded fallback continued.",
                    ),
                    degraded=True,
                ),
            )
        degraded = RecallStagePolicy.pack_is_degraded(
            warnings=temporal_view.warnings,
            effective_strategy=result.pack.effective_strategy,
            requested_strategy=strategy,
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
