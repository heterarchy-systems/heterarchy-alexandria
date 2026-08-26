"""Context recall strategy, pack assembly, and explain-only diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchExecutionTrace,
    ContextSearchExplainResult,
    ContextSearchTraceCollector,
)
from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.retrieval.context_pack import build_context_pack
from app.memory.application.retrieval.context_retrieval_lane_executor import (
    ContextRetrievalLaneExecutor,
)
from app.memory.application.retrieval.planning.context_memory_function_preference import (
    prefer_memory_function_matches,
    validated_memory_functions,
)
from app.memory.application.retrieval.planning.context_retrieval_plan_resolution import (
    resolve_context_retrieval_execution,
)
from app.memory.application.retrieval.planning.context_scope_filter import (
    filter_context_matches,
)
from app.memory.application.retrieval.planning.context_temporal_preference import (
    prefer_current_temporal_matches,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextRecallFilter,
    validated_scope_identity,
)
from app.memory.domain.entities.context_read_models import (
    ContextPack,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    MemoryFunction,
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    IContextRetrievalKernelProvider,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.memory.domain.repositories.contexts.graph.context_graph_candidate_expansion_provider import (
    IContextGraphCandidateExpansionProvider,
)
from app.memory.domain.repositories.contexts.graph.context_graph_signal_provider import (
    IContextGraphSignalProvider,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.types.types_convert_utils import enum_value


@dataclass(frozen=True, slots=True)
class _SearchExecution:
    """Internal search result with an optional explain-only trace."""

    pack: ContextPack
    trace: ContextSearchExecutionTrace | None


class ContextSearchService:
    """Validate recall identity, select retrieval strategy, and build Context packs."""

    def __init__(
        self,
        search_sources: list[IContextSearchSource],
        embedding_service: ContextEmbeddingService,
        retrieval_kernel_provider: IContextRetrievalKernelProvider,
        graph_signal_provider: IContextGraphSignalProvider | None = None,
        graph_candidate_expansion_provider: IContextGraphCandidateExpansionProvider
        | None = None,
    ) -> None:
        """Create the Context search service.

        Args:
            search_sources: Configured FTS and vector recall sources.
            embedding_service: Vector recall and dependency health collaborator.
            retrieval_kernel_provider: Single authoritative retrieval-ranking provider.
            graph_signal_provider: Optional score-preserving graph evidence provider.
            graph_candidate_expansion_provider: Optional AUTO-only multi-hop graph expansion provider.
        """
        self._embedding_service = embedding_service
        self._lane_executor = ContextRetrievalLaneExecutor(
            search_sources, embedding_service, retrieval_kernel_provider
        )
        self._graph_signal_provider = graph_signal_provider
        self._graph_candidate_expansion_provider = graph_candidate_expansion_provider

    async def search(
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
    ) -> ContextPack:
        """Return a Context pack for one query without diagnostic instrumentation.

        Args:
            query: Search query text.
            strategy: Requested retrieval strategy.
            limit: Maximum matches.
            project: Optional project filter.
            kind: Optional Context kind filter.
            include_scopes: Optional recall scope filters.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            include_lifecycle_statuses: Optional administrative lifecycle filter.
            prefer_memory_functions: Optional soft functional-memory preference.

        Returns:
            Context pack containing retrieved matches and warnings.
        """
        result = await self._execute(
            query=query,
            strategy=strategy,
            limit=limit,
            project=project,
            kind=kind,
            include_scopes=include_scopes,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            include_lifecycle_statuses=include_lifecycle_statuses,
            prefer_memory_functions=prefer_memory_functions,
            collect_trace=False,
        )
        return result.pack

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
        """Run the same retrieval path while collecting bounded operator diagnostics.

        Args:
            query: Search query text.
            strategy: Requested retrieval strategy.
            limit: Maximum matches.
            project: Optional project filter.
            kind: Optional Context kind filter.
            include_scopes: Optional recall scope filters.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            include_lifecycle_statuses: Optional administrative lifecycle filter.
            prefer_memory_functions: Optional soft functional-memory preference.

        Returns:
            Normal Context pack paired with execution diagnostics.
        """
        execution = await self._execute(
            query=query,
            strategy=strategy,
            limit=limit,
            project=project,
            kind=kind,
            include_scopes=include_scopes,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            include_lifecycle_statuses=include_lifecycle_statuses,
            prefer_memory_functions=prefer_memory_functions,
            collect_trace=True,
        )
        if execution.trace is None:
            raise RuntimeError("CONTEXT_SEARCH_TRACE_UNAVAILABLE")
        return ContextSearchExplainResult(pack=execution.pack, trace=execution.trace)

    async def _execute(
        self,
        query: str,
        strategy: RagStrategy,
        limit: int,
        project: str | None,
        kind: ContextKind | None,
        include_scopes: list[ContextScope] | None,
        workspace_id: str | None,
        agent_id: str | None,
        user_id: str | None,
        session_id: str | None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None,
        prefer_memory_functions: list[MemoryFunction] | None,
        collect_trace: bool,
    ) -> _SearchExecution:
        """Execute the shared Context retrieval pipeline with optional instrumentation.

        Args:
            query: Search query text.
            strategy: Requested retrieval strategy.
            limit: Maximum final match count.
            project: Optional project filter.
            kind: Optional Context kind filter.
            include_scopes: Optional recall scopes.
            workspace_id: Optional workspace identity.
            agent_id: Optional agent identity.
            user_id: Optional user identity.
            session_id: Optional session identity.
            include_lifecycle_statuses: Optional administrative lifecycle filters.
            prefer_memory_functions: Optional soft functional-memory preference.
            collect_trace: Whether explain-only counters and timings are collected.

        Returns:
            Internal Context pack and optional execution trace.

        Raises:
            MemoryContextValidationError: If query or scope identity validation fails.
        """
        if not query.strip():
            raise MemoryContextValidationError("query is required")
        strategy = enum_value(strategy, RagStrategy, "strategy")
        collector = (
            ContextSearchTraceCollector.create(
                requested_strategy=strategy,
                requested_limit=limit,
            )
            if collect_trace
            else None
        )
        if kind is not None:
            kind = enum_value(kind, ContextKind, "kind")
        include_scopes = [
            enum_value(scope, ContextScope, "include_scopes")
            for scope in (include_scopes or [])
        ]
        if not include_scopes:
            include_scopes = (
                [ContextScope.GLOBAL]
                if project is None
                else [ContextScope.PROJECT, ContextScope.GLOBAL]
            )
        if include_lifecycle_statuses is not None:
            include_lifecycle_statuses = [
                enum_value(
                    lifecycle_status,
                    ContextRecallLifecycleStatus,
                    "include_lifecycle_statuses",
                )
                for lifecycle_status in include_lifecycle_statuses
            ]
            if not include_lifecycle_statuses:
                include_lifecycle_statuses = None
        prefer_memory_functions = validated_memory_functions(prefer_memory_functions)
        selection = resolve_context_retrieval_execution(
            query, strategy, limit, prefer_memory_functions
        )
        effective = selection.strategy
        prefer_memory_functions = list(selection.preferred_memory_functions)
        if collector is not None:
            collector.retrieval_plan = selection.adaptive_plan
        try:
            scope_filter = validated_scope_identity(
                tuple(include_scopes),
                project,
                workspace_id,
                agent_id,
                user_id,
                session_id,
            )
        except ValueError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        recall_filter = ContextRecallFilter(
            limit=limit,
            kind=kind,
            scope_identity=scope_filter,
            lifecycle_statuses=(
                None
                if include_lifecycle_statuses is None
                else tuple(include_lifecycle_statuses)
            ),
        )
        warnings: list[str] = []
        if effective is not RagStrategy.FTS_ONLY:
            started_at = collector.start_timer() if collector is not None else 0.0
            health = await self._embedding_service.recall_health()
            if collector is not None:
                collector.embedding_health_ms += collector.elapsed_ms(started_at)
            warnings.extend(health.warnings)
            if (
                effective is RagStrategy.HYBRID
                and health.default_strategy is RagStrategy.FTS_ONLY
            ):
                effective = RagStrategy.FTS_ONLY
                warnings.append("Vector retrieval degraded; using FTS_ONLY.")
            if effective is RagStrategy.VECTOR_ONLY and (
                health.vector is not RagHealthState.HEALTHY
                or health.embedding is not RagHealthState.HEALTHY
            ):
                effective = RagStrategy.FTS_ONLY
                warnings.append(
                    "VECTOR_ONLY requested but vector dependencies are degraded; "
                    "using FTS_ONLY."
                )
        matches = await self._lane_executor.retrieve(
            query=query,
            effective=effective,
            limit=limit,
            recall_filter=recall_filter,
            adaptive_plan=selection.adaptive_plan,
            collector=collector,
        )
        started_at = collector.start_timer() if collector is not None else 0.0
        matches = filter_context_matches(matches, scope_filter)
        if collector is not None:
            collector.filter_ms += collector.elapsed_ms(started_at)
            collector.filtered_match_count = len(matches)
        if (
            selection.adaptive_plan is not None
            and selection.adaptive_plan.graph_enabled
            and self._graph_candidate_expansion_provider is not None
        ):
            expansion_started_at = (
                collector.start_timer() if collector is not None else 0.0
            )
            try:
                expansion = await self._graph_candidate_expansion_provider.expand(
                    query=query,
                    matches=matches,
                    recall_filter=recall_filter,
                    limit=limit,
                    graph_depth=selection.adaptive_plan.graph_depth,
                )
            except Exception as exc:
                warnings.append(
                    "Graph multi-hop expansion unavailable "
                    f"[GRAPH_EXPANSION_UNAVAILABLE; {_exception_class_name(exc)}]; "
                    "primary Context recall preserved."
                )
                if collector is not None:
                    collector.graph_expansion_degraded = True
            else:
                matches = list(expansion.matches)
                warnings.extend(expansion.warnings)
                if collector is not None:
                    collector.graph_expansion_discovered_candidate_count = (
                        expansion.discovered_candidate_count
                    )
                    collector.graph_expansion_selected_candidate_count = (
                        expansion.selected_candidate_count
                    )
                    collector.graph_expansion_hydrated_candidate_count = (
                        expansion.hydrated_candidate_count
                    )
                    collector.graph_expansion_filtered_candidate_count = (
                        expansion.filtered_candidate_count
                    )
                    collector.graph_expansion_appended_candidate_count = (
                        expansion.appended_candidate_count
                    )
                    collector.graph_expansion_applied = (
                        expansion.appended_candidate_count > 0
                    )
            finally:
                if collector is not None:
                    collector.graph_expansion_ms += collector.elapsed_ms(
                        expansion_started_at
                    )
        if selection.graph_enabled and self._graph_signal_provider is not None:
            primary_matches = matches
            started_at = collector.start_timer() if collector is not None else 0.0
            try:
                graph_result = await self._graph_signal_provider.enrich(matches)
            # The optional provider is a recovery boundary: adapter failures must
            # degrade to sanitized diagnostics without changing primary recall.
            except Exception as exc:
                warnings.append(
                    "Graph context lane unavailable "
                    f"[GRAPH_CONTEXT_UNAVAILABLE; {_exception_class_name(exc)}]; "
                    "primary Context recall preserved."
                )
                if collector is not None:
                    collector.graph_enrichment_degraded = True
            else:
                candidate_matches = list(graph_result.matches)
                if _preserves_primary_ranking(primary_matches, candidate_matches):
                    matches = candidate_matches
                    warnings.extend(graph_result.warnings)
                    if collector is not None:
                        collector.graph_enrichment_applied = True
                else:
                    warnings.append(
                        "Graph context lane returned invalid ranking; "
                        "primary Context recall preserved."
                    )
                    if collector is not None:
                        collector.graph_enrichment_degraded = True
            finally:
                if collector is not None:
                    collector.graph_ms += collector.elapsed_ms(started_at)
        if collector is not None:
            collector.graph_evidence_match_count = sum(
                bool(match.graph_evidence) for match in matches
            )
        matches = prefer_current_temporal_matches(
            matches,
            selection.temporal_current_preference,
        )
        matches = prefer_memory_function_matches(matches, prefer_memory_functions)
        started_at = collector.start_timer() if collector is not None else 0.0
        rendered_pack = build_context_pack(query=query, matches=matches)
        if collector is not None:
            collector.context_pack_ms += collector.elapsed_ms(started_at)
        pack = ContextPack(
            query=query,
            strategy=strategy,
            effective_strategy=effective,
            warnings=tuple(warnings),
            recall_scopes=tuple(include_scopes),
            matches=tuple(matches),
            context_pack=rendered_pack,
        )
        if collector is None:
            return _SearchExecution(pack=pack, trace=None)
        return _SearchExecution(pack=pack, trace=collector.finish(effective))


def _preserves_primary_ranking(
    primary: list[ContextSearchMatch],
    enriched: list[ContextSearchMatch],
) -> bool:
    """Return whether graph enrichment preserved primary retrieval ranking.

    Args:
        primary: Primary matches before graph enrichment.
        enriched: Candidate graph-enriched matches.

    Returns:
        Whether Context, chunk, and score ordering is unchanged.
    """
    return [
        (
            match.context,
            match.chunk,
            match.score,
            match.fts_score,
            match.vector_score,
            match.graph_score,
        )
        for match in primary
    ] == [
        (
            match.context,
            match.chunk,
            match.score,
            match.fts_score,
            match.vector_score,
            match.graph_score,
        )
        for match in enriched
    ]


def _exception_class_name(exc: Exception) -> str:
    """Return a bounded ASCII exception class name for operator diagnostics.

    Args:
        exc: Exception raised by the underlying operation.

    Returns:
        Sanitized exception class name.
    """
    class_name = type(exc).__name__
    sanitized = "".join(
        character
        for character in class_name
        if character.isascii() and (character.isalnum() or character == "_")
    )
    return (sanitized or "Exception")[:80]
