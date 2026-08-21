"""Context recall strategy and pack assembly service."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.retrieval.context_pack import build_context_pack
from app.memory.application.retrieval.planning.context_query_planning import (
    context_query_variants,
)
from app.memory.application.retrieval.planning.context_scope_filter import (
    filter_context_matches,
)
from app.memory.application.retrieval.ranking.context_ranking import (
    hybrid_candidate_limit,
    merge_hybrid_matches,
    rank_best_matches_per_context,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
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
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.repositories.contexts.context_graph_signal_provider import (
    IContextGraphSignalProvider,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.types.types_convert_utils import enum_value


class ContextSearchService:
    """Validate recall identity, select retrieval strategy, and build Context packs."""

    def __init__(
        self,
        search_sources: list[IContextSearchSource],
        embedding_service: ContextEmbeddingService,
        graph_signal_provider: IContextGraphSignalProvider | None = None,
    ) -> None:
        """Create the Context search service.

        Args:
            search_sources: Configured FTS and vector recall sources.
            embedding_service: Vector recall and dependency health collaborator.
            graph_signal_provider: Optional score-preserving graph evidence provider.
        """
        self._search_sources = search_sources
        self._embedding_service = embedding_service
        self._graph_signal_provider = graph_signal_provider

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
    ) -> ContextPack:
        """Return a Context pack for one query.

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

        Returns:
            Context pack containing retrieved matches and warnings.
        """
        if not query.strip():
            raise MemoryContextValidationError("query is required")
        strategy = enum_value(strategy, RagStrategy, "strategy")
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
        health = await self._embedding_service.health_with_index_status()
        effective = strategy
        warnings = list(health.warnings)
        if (
            strategy is RagStrategy.HYBRID
            and health.default_strategy is RagStrategy.FTS_ONLY
        ):
            effective = RagStrategy.FTS_ONLY
            warnings.append("Vector retrieval degraded; using FTS_ONLY.")
        if strategy is RagStrategy.VECTOR_ONLY and (
            health.vector is not RagHealthState.HEALTHY
            or health.embedding is not RagHealthState.HEALTHY
        ):
            effective = RagStrategy.FTS_ONLY
            warnings.append(
                "VECTOR_ONLY requested but vector dependencies are degraded; "
                "using FTS_ONLY."
            )
        if effective is RagStrategy.FTS_ONLY:
            matches = await self._search_fts_sources(
                ContextFtsRecall(query=query, recall_filter=recall_filter)
            )
        elif effective is RagStrategy.VECTOR_ONLY:
            matches = await self._embedding_service.search_vector(
                query=query,
                recall_filter=recall_filter,
            )
        else:
            candidate_filter = replace(
                recall_filter,
                limit=hybrid_candidate_limit(limit),
            )
            fts_matches = await self._search_fts_sources(
                ContextFtsRecall(query=query, recall_filter=candidate_filter)
            )
            vector_matches = await self._embedding_service.search_vector(
                query=query,
                recall_filter=candidate_filter,
            )
            matches = merge_hybrid_matches(
                fts_matches=fts_matches,
                vector_matches=vector_matches,
                limit=limit,
            )
        matches = filter_context_matches(matches, scope_filter)
        if self._graph_signal_provider is not None:
            primary_matches = matches
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
            else:
                candidate_matches = list(graph_result.matches)
                if _preserves_primary_ranking(primary_matches, candidate_matches):
                    matches = candidate_matches
                    warnings.extend(graph_result.warnings)
                else:
                    warnings.append(
                        "Graph context lane returned invalid ranking; "
                        "primary Context recall preserved."
                    )
        return ContextPack(
            query=query,
            strategy=strategy,
            effective_strategy=effective,
            warnings=tuple(warnings),
            recall_scopes=tuple(include_scopes),
            matches=tuple(matches),
            context_pack=build_context_pack(query=query, matches=matches),
        )

    async def _search_fts_sources(
        self,
        recall: ContextFtsRecall,
    ) -> list[ContextSearchMatch]:
        matches_by_context_id: dict[str, ContextSearchMatch] = {}
        for query_variant in context_query_variants(recall.query):
            variant_matches: list[ContextSearchMatch] = []
            variant_recall = ContextFtsRecall(
                query=query_variant,
                recall_filter=recall.recall_filter,
            )
            for source in self._search_sources:
                variant_matches.extend(await source.search_fts(variant_recall))
            ranked_variant = rank_best_matches_per_context(
                variant_matches,
                recall.recall_filter.limit,
            )
            for match in ranked_variant:
                matches_by_context_id.setdefault(match.context.id, match)
                if len(matches_by_context_id) >= recall.recall_filter.limit:
                    return list(matches_by_context_id.values())
        return list(matches_by_context_id.values())


def _preserves_primary_ranking(
    primary: list[ContextSearchMatch],
    enriched: list[ContextSearchMatch],
) -> bool:
    return [
        (
            match.context,
            match.chunk,
            match.score,
            match.fts_score,
            match.vector_score,
        )
        for match in primary
    ] == [
        (
            match.context,
            match.chunk,
            match.score,
            match.fts_score,
            match.vector_score,
        )
        for match in enriched
    ]


def _exception_class_name(exc: Exception) -> str:
    class_name = type(exc).__name__
    sanitized = "".join(
        character
        for character in class_name
        if character.isascii() and (character.isalnum() or character == "_")
    )
    return (sanitized or "Exception")[:80]
