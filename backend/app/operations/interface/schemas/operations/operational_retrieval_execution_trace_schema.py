"""Focused strict schemas for Context retrieval fusion and stage timings."""

from __future__ import annotations

from typing import Annotated

from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchTimingTrace,
)
from app.memory.domain.repositories.contexts.context_retrieval_kernel_provider import (
    ContextRetrievalFusionTrace,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class OperationalRetrievalFusionTraceResponse(StrictSchemaModel):
    """Deterministic Rust hybrid-fusion counters."""

    fts_input_count: Annotated[int, described_field("Input FTS candidate rows.", ge=0)]
    vector_input_count: Annotated[
        int, described_field("Input vector candidate rows.", ge=0)
    ]
    fts_unique_count: Annotated[
        int, described_field("Distinct FTS Context identities.", ge=0)
    ]
    vector_unique_count: Annotated[
        int, described_field("Distinct vector Context identities.", ge=0)
    ]
    fts_duplicate_count: Annotated[
        int, described_field("Duplicate FTS rows after rank consumption.", ge=0)
    ]
    vector_duplicate_count: Annotated[
        int, described_field("Duplicate vector rows after rank consumption.", ge=0)
    ]
    fused_candidate_count: Annotated[
        int,
        described_field("Distinct identities across both lanes before top-k.", ge=0),
    ]
    cross_lane_count: Annotated[
        int, described_field("Identities carrying evidence from both lanes.", ge=0)
    ]
    returned_count: Annotated[
        int, described_field("Results returned after top-k truncation.", ge=0)
    ]
    representative_fts_count: Annotated[
        int, described_field("Returned results represented by the FTS lane.", ge=0)
    ]
    representative_vector_count: Annotated[
        int, described_field("Returned results represented by the vector lane.", ge=0)
    ]

    @classmethod
    def from_entity(
        cls,
        trace: ContextRetrievalFusionTrace,
    ) -> OperationalRetrievalFusionTraceResponse:
        """Map one native fusion trace to the strict HTTP contract.

        Args:
            trace: Typed native fusion diagnostics.

        Returns:
            Strict fusion trace response.
        """
        return cls(
            fts_input_count=trace.fts_input_count,
            vector_input_count=trace.vector_input_count,
            fts_unique_count=trace.fts_unique_count,
            vector_unique_count=trace.vector_unique_count,
            fts_duplicate_count=trace.fts_duplicate_count,
            vector_duplicate_count=trace.vector_duplicate_count,
            fused_candidate_count=trace.fused_candidate_count,
            cross_lane_count=trace.cross_lane_count,
            returned_count=trace.returned_count,
            representative_fts_count=trace.representative_fts_count,
            representative_vector_count=trace.representative_vector_count,
        )


class OperationalRetrievalTimingTraceResponse(StrictSchemaModel):
    """Explain-only wall-clock timings in milliseconds."""

    embedding_health_ms: Annotated[
        float, described_field("Embedding health time.", ge=0)
    ]
    fts_ms: Annotated[float, described_field("FTS retrieval time.", ge=0)]
    vector_ms: Annotated[float, described_field("Vector retrieval time.", ge=0)]
    fusion_ms: Annotated[float, described_field("Native fusion time.", ge=0)]
    filter_ms: Annotated[float, described_field("Scope filtering time.", ge=0)]
    graph_ms: Annotated[float, described_field("Graph enrichment time.", ge=0)]
    graph_expansion_ms: Annotated[
        float, described_field("AUTO multi-hop graph expansion time.", ge=0)
    ]
    context_pack_ms: Annotated[
        float, described_field("Context Pack rendering time.", ge=0)
    ]
    total_ms: Annotated[
        float, described_field("End-to-end explained search time.", ge=0)
    ]

    @classmethod
    def from_entity(
        cls,
        trace: ContextSearchTimingTrace,
    ) -> OperationalRetrievalTimingTraceResponse:
        """Map application timing diagnostics to the strict HTTP contract.

        Args:
            trace: Explain-only search stage timings.

        Returns:
            Strict timing response.
        """
        return cls(
            embedding_health_ms=trace.embedding_health_ms,
            fts_ms=trace.fts_ms,
            vector_ms=trace.vector_ms,
            fusion_ms=trace.fusion_ms,
            filter_ms=trace.filter_ms,
            graph_ms=trace.graph_ms,
            graph_expansion_ms=trace.graph_expansion_ms,
            context_pack_ms=trace.context_pack_ms,
            total_ms=trace.total_ms,
        )
