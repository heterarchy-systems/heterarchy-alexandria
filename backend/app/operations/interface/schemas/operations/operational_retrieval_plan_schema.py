"""Strict operator response contract for deterministic adaptive retrieval plans."""

from __future__ import annotations

from typing import Annotated

from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ContextRetrievalPlan,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRetrievalFusionProfile,
    ContextRetrievalIntent,
    MemoryFunction,
    RagStrategy,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class OperationalRetrievalPlanResponse(StrictSchemaModel):
    """Bounded deterministic AUTO planner metadata without query bodies or vectors."""

    profile_version: Annotated[
        str, described_field("Adaptive planner profile version.")
    ]
    intent: Annotated[
        ContextRetrievalIntent, described_field("Deterministic query intent.")
    ]
    strategy: Annotated[
        RagStrategy, described_field("Fixed primary lane selected by AUTO.")
    ]
    lexical_enabled: Annotated[
        bool, described_field("Whether lexical recall is enabled.")
    ]
    vector_enabled: Annotated[
        bool, described_field("Whether vector recall is enabled.")
    ]
    graph_enabled: Annotated[
        bool, described_field("Whether graph enrichment is enabled.")
    ]
    fts_budget: Annotated[
        int, described_field("Planned FTS candidate budget.", ge=0, le=50)
    ]
    vector_budget: Annotated[
        int, described_field("Planned vector candidate budget.", ge=0, le=50)
    ]
    graph_depth: Annotated[
        int, described_field("Planned graph depth for v1.", ge=0, le=2)
    ]
    candidate_multiplier: Annotated[
        int, described_field("Planned candidate multiplier.", ge=1)
    ]
    fusion_profile: Annotated[
        ContextRetrievalFusionProfile,
        described_field("Deterministic fusion profile selected by the planner."),
    ]
    top_k: Annotated[int, described_field("Requested final result count.", ge=1, le=50)]
    preferred_memory_functions: Annotated[
        list[MemoryFunction],
        described_field("Soft functional-memory preferences selected for recall."),
    ]
    temporal_current_preference: Annotated[
        bool,
        described_field("Whether the plan detected current-state temporal intent."),
    ]
    reasons: Annotated[
        list[str],
        described_field("Bounded deterministic planner reason codes."),
    ]

    @classmethod
    def from_entity(
        cls, plan: ContextRetrievalPlan
    ) -> OperationalRetrievalPlanResponse:
        """Map one pure planner result into bounded operator diagnostics.

        Args:
            plan: Deterministic adaptive retrieval plan.

        Returns:
            Strict operator-facing plan metadata.
        """
        return cls(
            profile_version=plan.profile_version,
            intent=plan.intent,
            strategy=plan.strategy,
            lexical_enabled=plan.lexical_enabled,
            vector_enabled=plan.vector_enabled,
            graph_enabled=plan.graph_enabled,
            fts_budget=plan.fts_budget,
            vector_budget=plan.vector_budget,
            graph_depth=plan.graph_depth,
            candidate_multiplier=plan.candidate_multiplier,
            fusion_profile=plan.fusion_profile,
            top_k=plan.top_k,
            preferred_memory_functions=list(plan.preferred_memory_functions),
            temporal_current_preference=plan.temporal_current_preference,
            reasons=list(plan.reasons),
        )
