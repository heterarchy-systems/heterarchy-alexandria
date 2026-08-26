"""Primary Context retrieval lane execution and bounded Hybrid fusion."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchTraceCollector,
)
from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ContextRetrievalPlan,
)
from app.memory.application.retrieval.planning.context_query_planning import (
    context_query_variants,
)
from app.memory.application.retrieval.planning.context_retrieval_plan_resolution import (
    bounded_auto_hybrid_budgets,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextRecallFilter,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    IContextRetrievalKernelProvider,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)


class ContextRetrievalLaneExecutor:
    """Execute fixed FTS/vector lanes and Rust-authoritative Hybrid fusion."""

    def __init__(
        self,
        search_sources: list[IContextSearchSource],
        embedding_service: ContextEmbeddingService,
        retrieval_kernel_provider: IContextRetrievalKernelProvider,
    ) -> None:
        """Create one retrieval lane executor.

        Args:
            search_sources: Configured FTS sources.
            embedding_service: Vector retrieval collaborator.
            retrieval_kernel_provider: Rust-authoritative ranking/fusion provider.
        """
        self._search_sources = search_sources
        self._embedding_service = embedding_service
        self._retrieval_kernel_provider = retrieval_kernel_provider

    async def retrieve(
        self,
        query: str,
        effective: RagStrategy,
        limit: int,
        recall_filter: ContextRecallFilter,
        adaptive_plan: ContextRetrievalPlan | None,
        collector: ContextSearchTraceCollector | None,
    ) -> list[ContextSearchMatch]:
        """Execute one resolved fixed lane and optional traced Hybrid fusion.

        Args:
            query: Search query text.
            effective: Fixed retrieval strategy selected after planning/health checks.
            limit: Maximum final match count.
            recall_filter: Validated Context recall filters.
            adaptive_plan: Optional AUTO plan supplying bounded source budgets.
            collector: Optional explain-only diagnostic accumulator.

        Returns:
            Ranked Context matches from the effective retrieval strategy.
        """
        if effective is RagStrategy.AUTO:
            raise ValueError("AUTO must be resolved before retrieval lane execution")
        if effective is RagStrategy.FTS_ONLY:
            return await self._retrieve_fts(query, recall_filter, collector)
        if effective is RagStrategy.VECTOR_ONLY:
            return await self._retrieve_vector(query, recall_filter, collector)
        return await self._retrieve_hybrid(
            query,
            limit,
            recall_filter,
            adaptive_plan,
            collector,
        )

    async def _retrieve_fts(
        self,
        query: str,
        recall_filter: ContextRecallFilter,
        collector: ContextSearchTraceCollector | None,
    ) -> list[ContextSearchMatch]:
        """Execute lexical recall and record explain-only counters.

        Args:
            query: Search query text.
            recall_filter: Validated Context recall filters.
            collector: Optional explain-only diagnostics collector.

        Returns:
            Ranked lexical matches.
        """
        started_at = collector.start_timer() if collector is not None else 0.0
        matches = await self._search_fts_sources(
            ContextFtsRecall(query=query, recall_filter=recall_filter),
            collector,
        )
        if collector is not None:
            collector.fts_ms += collector.elapsed_ms(started_at)
            collector.post_fusion_match_count = len(matches)
        return matches

    async def _retrieve_vector(
        self,
        query: str,
        recall_filter: ContextRecallFilter,
        collector: ContextSearchTraceCollector | None,
    ) -> list[ContextSearchMatch]:
        """Execute semantic vector recall and record explain-only counters.

        Args:
            query: Search query text.
            recall_filter: Validated Context recall filters.
            collector: Optional explain-only diagnostics collector.

        Returns:
            Ranked vector matches.
        """
        started_at = collector.start_timer() if collector is not None else 0.0
        matches = await self._embedding_service.search_vector(
            query=query,
            recall_filter=recall_filter,
        )
        if collector is not None:
            collector.vector_ms += collector.elapsed_ms(started_at)
            collector.vector_candidate_count = len(matches)
            collector.post_fusion_match_count = len(matches)
        return matches

    async def _retrieve_hybrid(
        self,
        query: str,
        limit: int,
        recall_filter: ContextRecallFilter,
        adaptive_plan: ContextRetrievalPlan | None,
        collector: ContextSearchTraceCollector | None,
    ) -> list[ContextSearchMatch]:
        """Execute bounded lexical/vector recall followed by Rust Hybrid fusion.

        Args:
            query: Search query text.
            limit: Maximum final match count.
            recall_filter: Validated Context recall filters.
            adaptive_plan: Optional AUTO plan supplying source budgets.
            collector: Optional explain-only diagnostics collector.

        Returns:
            Deterministically fused Hybrid matches.
        """
        native_limit = self._retrieval_kernel_provider.hybrid_candidate_limit(limit)
        fts_limit, vector_limit = bounded_auto_hybrid_budgets(
            adaptive_plan,
            native_limit,
            limit,
        )
        if collector is not None:
            collector.hybrid_candidate_limit = max(fts_limit, vector_limit)
        fts_filter = replace(recall_filter, limit=fts_limit)
        vector_filter = replace(recall_filter, limit=vector_limit)
        started_at = collector.start_timer() if collector is not None else 0.0
        fts_matches = await self._search_fts_sources(
            ContextFtsRecall(query=query, recall_filter=fts_filter),
            collector,
        )
        if collector is not None:
            collector.fts_ms += collector.elapsed_ms(started_at)
        started_at = collector.start_timer() if collector is not None else 0.0
        vector_matches = await self._embedding_service.search_vector(
            query=query,
            recall_filter=vector_filter,
        )
        if collector is not None:
            collector.vector_ms += collector.elapsed_ms(started_at)
            collector.vector_candidate_count = len(vector_matches)
            started_at = collector.start_timer()
            result = self._retrieval_kernel_provider.merge_with_trace(
                fts_matches=fts_matches,
                vector_matches=vector_matches,
                limit=limit,
            )
            collector.fusion_ms += collector.elapsed_ms(started_at)
            collector.kernel_fusion = result.trace
            collector.post_fusion_match_count = len(result.matches)
            return list(result.matches)
        return self._retrieval_kernel_provider.merge(
            fts_matches=fts_matches,
            vector_matches=vector_matches,
            limit=limit,
        )

    async def _search_fts_sources(
        self,
        recall: ContextFtsRecall,
        collector: ContextSearchTraceCollector | None,
    ) -> list[ContextSearchMatch]:
        """Search FTS sources using deterministic query variants.

        Args:
            recall: Validated FTS recall request.
            collector: Optional explain-only diagnostic accumulator.

        Returns:
            First non-empty variant ranked to the requested Context limit.
        """
        for query_variant in context_query_variants(recall.query):
            if collector is not None:
                collector.fts_query_variants_attempted += 1
            variant_matches: list[ContextSearchMatch] = []
            variant_recall = ContextFtsRecall(
                query=query_variant,
                recall_filter=recall.recall_filter,
            )
            for source in self._search_sources:
                source_matches = await source.search_fts(variant_recall)
                variant_matches.extend(source_matches)
                if collector is not None:
                    collector.fts_source_calls += 1
                    collector.fts_source_candidate_count += len(source_matches)
            ranked_variant = self._retrieval_kernel_provider.rank_best(
                variant_matches,
                recall.recall_filter.limit,
            )
            if ranked_variant:
                if collector is not None:
                    collector.fts_ranked_candidate_count = len(ranked_variant)
                return ranked_variant
        return []
