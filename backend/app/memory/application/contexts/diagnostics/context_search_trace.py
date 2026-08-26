"""Typed operator diagnostics for one Context retrieval execution."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ContextRetrievalPlan,
)
from app.memory.domain.entities.context_read_models import ContextPack
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    ContextRetrievalFusionTrace,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSearchTimingTrace:
    """Wall-clock stage timings collected only for an explained search."""

    embedding_health_ms: float
    fts_ms: float
    vector_ms: float
    fusion_ms: float
    filter_ms: float
    graph_ms: float
    context_pack_ms: float
    total_ms: float
    graph_expansion_ms: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSearchExecutionTrace:
    """Bounded retrieval diagnostics that exclude embeddings and raw database payloads."""

    requested_strategy: RagStrategy
    effective_strategy: RagStrategy
    requested_limit: int
    hybrid_candidate_limit: int | None
    fts_source_calls: int
    fts_query_variants_attempted: int
    fts_source_candidate_count: int
    fts_ranked_candidate_count: int
    vector_candidate_count: int
    post_fusion_match_count: int
    filtered_match_count: int
    graph_evidence_match_count: int
    graph_enrichment_applied: bool
    graph_enrichment_degraded: bool
    kernel_fusion: ContextRetrievalFusionTrace | None
    timings: ContextSearchTimingTrace
    retrieval_plan: ContextRetrievalPlan | None = None
    graph_expansion_discovered_candidate_count: int = 0
    graph_expansion_selected_candidate_count: int = 0
    graph_expansion_hydrated_candidate_count: int = 0
    graph_expansion_filtered_candidate_count: int = 0
    graph_expansion_appended_candidate_count: int = 0
    graph_expansion_applied: bool = False
    graph_expansion_degraded: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSearchExplainResult:
    """Normal Context pack paired with operator-only execution diagnostics."""

    pack: ContextPack
    trace: ContextSearchExecutionTrace


@dataclass(slots=True)
class ContextSearchTraceCollector:
    """Mutable request-local counters allocated only for explained search execution."""

    requested_strategy: RagStrategy
    requested_limit: int
    total_started_at: float
    hybrid_candidate_limit: int | None = None
    fts_source_calls: int = 0
    fts_query_variants_attempted: int = 0
    fts_source_candidate_count: int = 0
    fts_ranked_candidate_count: int = 0
    vector_candidate_count: int = 0
    post_fusion_match_count: int = 0
    filtered_match_count: int = 0
    graph_evidence_match_count: int = 0
    graph_enrichment_applied: bool = False
    graph_enrichment_degraded: bool = False
    graph_expansion_discovered_candidate_count: int = 0
    graph_expansion_selected_candidate_count: int = 0
    graph_expansion_hydrated_candidate_count: int = 0
    graph_expansion_filtered_candidate_count: int = 0
    graph_expansion_appended_candidate_count: int = 0
    graph_expansion_applied: bool = False
    graph_expansion_degraded: bool = False
    kernel_fusion: ContextRetrievalFusionTrace | None = None
    retrieval_plan: ContextRetrievalPlan | None = None
    embedding_health_ms: float = 0.0
    fts_ms: float = 0.0
    vector_ms: float = 0.0
    fusion_ms: float = 0.0
    filter_ms: float = 0.0
    graph_ms: float = 0.0
    graph_expansion_ms: float = 0.0
    context_pack_ms: float = 0.0

    @classmethod
    def create(
        cls,
        requested_strategy: RagStrategy,
        requested_limit: int,
    ) -> ContextSearchTraceCollector:
        """Create one explain-only collector and start its end-to-end timer.

        Args:
            requested_strategy: Retrieval strategy requested by the caller.
            requested_limit: Maximum result count requested by the caller.

        Returns:
            Mutable request-local trace collector.
        """
        return cls(
            requested_strategy=requested_strategy,
            requested_limit=requested_limit,
            total_started_at=perf_counter(),
        )

    @staticmethod
    def start_timer() -> float:
        """Start one explain-only stage timer.

        Returns:
            Monotonic ``perf_counter`` start value.
        """
        return perf_counter()

    @staticmethod
    def elapsed_ms(started_at: float) -> float:
        """Return non-negative elapsed milliseconds for one explained stage.

        Args:
            started_at: Monotonic ``perf_counter`` start value.

        Returns:
            Non-negative elapsed milliseconds.
        """
        return max(0.0, (perf_counter() - started_at) * 1000.0)

    def finish(self, effective_strategy: RagStrategy) -> ContextSearchExecutionTrace:
        """Freeze current counters into the public application trace.

        Args:
            effective_strategy: Strategy actually executed after health degradation.

        Returns:
            Immutable operator diagnostic snapshot.
        """
        return ContextSearchExecutionTrace(
            requested_strategy=self.requested_strategy,
            effective_strategy=effective_strategy,
            requested_limit=self.requested_limit,
            hybrid_candidate_limit=self.hybrid_candidate_limit,
            fts_source_calls=self.fts_source_calls,
            fts_query_variants_attempted=self.fts_query_variants_attempted,
            fts_source_candidate_count=self.fts_source_candidate_count,
            fts_ranked_candidate_count=self.fts_ranked_candidate_count,
            vector_candidate_count=self.vector_candidate_count,
            post_fusion_match_count=self.post_fusion_match_count,
            filtered_match_count=self.filtered_match_count,
            graph_evidence_match_count=self.graph_evidence_match_count,
            graph_enrichment_applied=self.graph_enrichment_applied,
            graph_enrichment_degraded=self.graph_enrichment_degraded,
            graph_expansion_discovered_candidate_count=(
                self.graph_expansion_discovered_candidate_count
            ),
            graph_expansion_selected_candidate_count=(
                self.graph_expansion_selected_candidate_count
            ),
            graph_expansion_hydrated_candidate_count=(
                self.graph_expansion_hydrated_candidate_count
            ),
            graph_expansion_filtered_candidate_count=(
                self.graph_expansion_filtered_candidate_count
            ),
            graph_expansion_appended_candidate_count=(
                self.graph_expansion_appended_candidate_count
            ),
            graph_expansion_applied=self.graph_expansion_applied,
            graph_expansion_degraded=self.graph_expansion_degraded,
            kernel_fusion=self.kernel_fusion,
            timings=ContextSearchTimingTrace(
                embedding_health_ms=self.embedding_health_ms,
                fts_ms=self.fts_ms,
                vector_ms=self.vector_ms,
                fusion_ms=self.fusion_ms,
                filter_ms=self.filter_ms,
                graph_ms=self.graph_ms,
                context_pack_ms=self.context_pack_ms,
                total_ms=self.elapsed_ms(self.total_started_at),
                graph_expansion_ms=self.graph_expansion_ms,
            ),
            retrieval_plan=self.retrieval_plan,
        )
