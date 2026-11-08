"""Strict operator response contract for deterministic adaptive retrieval plans."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.application.retrieval.planning.context_adaptive_retrieval_planner import (
    ContextRetrievalPlan,
)
from app.memory.domain.event_enum.context_enums import (
    ContextRetrievalFusionProfile,
    ContextRetrievalIntent,
    MemoryFunction,
    RagStrategy,
)
from app.shared.schemas.common_schemas import StrictSchemaModel


class OperationalRetrievalPlanResponse(StrictSchemaModel):
    """Bounded deterministic AUTO planner metadata without query bodies or vectors."""

    profile_version: Annotated[
        str, Field(description="Adaptive planner profile version.")
    ]
    intent: Annotated[
        ContextRetrievalIntent, Field(description="Deterministic query intent.")
    ]
    strategy: Annotated[
        RagStrategy, Field(description="Fixed primary lane selected by AUTO.")
    ]
    lexical_enabled: Annotated[
        bool, Field(description="Whether lexical recall is enabled.")
    ]
    vector_enabled: Annotated[
        bool, Field(description="Whether vector recall is enabled.")
    ]
    graph_enabled: Annotated[
        bool, Field(description="Whether graph enrichment is enabled.")
    ]
    fts_budget: Annotated[
        int, Field(description="Planned FTS candidate budget.", ge=0, le=50)
    ]
    vector_budget: Annotated[
        int, Field(description="Planned vector candidate budget.", ge=0, le=50)
    ]
    graph_depth: Annotated[
        int, Field(description="Planned graph depth for v1.", ge=0, le=2)
    ]
    candidate_multiplier: Annotated[
        int, Field(description="Planned candidate multiplier.", ge=1)
    ]
    fusion_profile: Annotated[
        ContextRetrievalFusionProfile,
        Field(description="Deterministic fusion profile selected by the planner."),
    ]
    top_k: Annotated[
        int, Field(description="Requested final result count.", ge=1, le=50)
    ]
    preferred_memory_functions: Annotated[
        list[MemoryFunction],
        Field(description="Soft functional-memory preferences selected for recall."),
    ]
    temporal_current_preference: Annotated[
        bool,
        Field(description="Whether the plan detected current-state temporal intent."),
    ]
    reasons: Annotated[
        list[str],
        Field(description="Bounded deterministic planner reason codes."),
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
