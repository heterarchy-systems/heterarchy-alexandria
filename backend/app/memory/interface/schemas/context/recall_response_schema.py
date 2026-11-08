"""Pydantic HTTP and MCP response contracts for high-level memory recall."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.domain.entities.recall import RecallResult, RecallTrace
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)
from app.memory.interface.schemas.context.context_mapping import match_payload
from app.memory.interface.schemas.context.context_search_schema import (
    ContextSearchMatchResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, exclude_none_field


class RecallProvenanceResponse(StrictSchemaModel):
    """Bounded evidence explaining one high-level recall match."""

    route: Annotated[RecallRoute, Field(description="Recall route used for the match.")]
    project_affinity: Annotated[
        RecallProjectAffinity,
        Field(description="Primary, related, or global project affinity."),
    ]
    canonical_context_id: Annotated[
        str,
        Field(description="Canonical Context identifier."),
    ]
    authority: Annotated[
        str,
        Field(description="Declared memory authority or UNKNOWN."),
    ]
    chunk_id: Annotated[str, Field(description="Matched chunk identifier.")]
    heading: Annotated[
        str | None,
        Field(description="Matched heading when available."),
        exclude_none_field(),
    ] = None
    project: Annotated[
        str | None,
        Field(description="Matched project when available."),
        exclude_none_field(),
    ] = None
    fts_score: Annotated[
        float | None,
        Field(description="Existing FTS contribution when available."),
        exclude_none_field(),
    ] = None
    vector_score: Annotated[
        float | None,
        Field(description="Existing vector contribution when available."),
        exclude_none_field(),
    ] = None
    graph_score: Annotated[
        float | None,
        Field(description="Existing graph contribution when available."),
        exclude_none_field(),
    ] = None
    confidence: Annotated[float, Field(description="Bounded evidence confidence.")]
    exact_contribution: Annotated[
        str | None,
        Field(description="Exact selector contribution when used."),
        exclude_none_field(),
    ] = None
    source_revision: Annotated[
        str | None,
        Field(description="Source revision when the source supplied one."),
        exclude_none_field(),
    ] = None
    index_revision: Annotated[
        str | None,
        Field(description="Index revision when the source supplied one."),
        exclude_none_field(),
    ] = None
    lifecycle_eligible: Annotated[
        bool, Field(description="Whether lifecycle eligibility was satisfied.")
    ]
    temporal_eligible: Annotated[
        bool | None,
        Field(description="Temporal eligibility when evaluated."),
        exclude_none_field(),
    ] = None
    title_alias_contribution: Annotated[
        str | None,
        Field(description="Title or alias contribution when available."),
        exclude_none_field(),
    ] = None


class RecallMatchResponse(StrictSchemaModel):
    """One existing Context match with high-level provenance."""

    match: Annotated[
        ContextSearchMatchResponse,
        Field(description="Existing Context search match."),
    ]
    provenance: Annotated[
        RecallProvenanceResponse,
        Field(description="Bounded recall provenance."),
    ]


class RecallStageTraceResponse(StrictSchemaModel):
    """One attempted or skipped high-level recall stage."""

    route: Annotated[RecallRoute, Field(description="Recall stage route.")]
    status: Annotated[RecallStageStatus, Field(description="Recall stage status.")]
    hit_count: Annotated[int, Field(description="Number of stage hits.", ge=0)]
    project: Annotated[
        str | None,
        Field(description="Project used by the stage."),
        exclude_none_field(),
    ] = None
    effective_strategy: Annotated[
        str | None,
        Field(description="Existing effective retrieval strategy."),
        exclude_none_field(),
    ] = None
    reason: Annotated[
        str | None,
        Field(description="Bounded stage reason."),
        exclude_none_field(),
    ] = None
    warnings: Annotated[list[str], Field(description="Stage warnings.")]
    degraded: Annotated[bool, Field(description="Whether the stage degraded.")]


class RecallTraceResponse(StrictSchemaModel):
    """Compact route and fallback trace for high-level recall."""

    stages: Annotated[
        list[RecallStageTraceResponse], Field(description="Recall stage trace.")
    ]
    skipped_scopes: Annotated[
        list[str], Field(description="Unavailable AUTO scope lanes skipped.")
    ]
    fallback_expansion: Annotated[
        list[RecallRoute], Field(description="Fallback routes that were attempted.")
    ]
    degraded_subsystems: Annotated[
        list[str], Field(description="Degraded subsystem identifiers.")
    ]
    outcome: Annotated[RecallOutcome, Field(description="Bounded recall outcome.")]
    confidence: Annotated[float, Field(description="Highest returned confidence.")]
    search_call_count: Annotated[
        int, Field(description="Number of existing search authority calls.", ge=0)
    ]


class RecallResponseSchema(StrictSchemaModel):
    """Agent-facing high-level recall response."""

    query: Annotated[str, Field(description="Normalized recall query.")]
    scope_mode: Annotated[
        RecallScopeMode, Field(description="Scope resolution mode used.")
    ]
    recall_scopes: Annotated[
        list[ContextScope], Field(description="Effective recall scope lanes.")
    ]
    effective_strategy: Annotated[
        str, Field(description="Last effective retrieval strategy used.")
    ]
    outcome: Annotated[RecallOutcome, Field(description="Bounded recall outcome.")]
    warnings: Annotated[list[str], Field(description="Recall warnings.")]
    matches: Annotated[
        list[RecallMatchResponse], Field(description="Recalled Context matches.")
    ]
    context_pack: Annotated[str, Field(description="Rendered bounded Context Pack.")]
    trace: Annotated[RecallTraceResponse, Field(description="Compact recall trace.")]

    @classmethod
    def from_entity(cls, result: RecallResult) -> RecallResponseSchema:
        """Build a strict response from the typed recall result."""
        return cls(
            query=result.query,
            scope_mode=result.scope_mode,
            recall_scopes=list(result.recall_scopes),
            effective_strategy=result.effective_strategy.value,
            outcome=result.outcome,
            warnings=list(result.warnings),
            matches=[
                RecallMatchResponse(
                    match=ContextSearchMatchResponse.model_validate(
                        match_payload(item.match)
                    ),
                    provenance=RecallProvenanceResponse(
                        route=item.provenance.route,
                        project_affinity=item.provenance.project_affinity,
                        canonical_context_id=item.provenance.canonical_context_id,
                        authority=item.provenance.authority,
                        chunk_id=item.provenance.chunk_id,
                        heading=item.provenance.heading,
                        project=item.provenance.project,
                        fts_score=item.provenance.fts_score,
                        vector_score=item.provenance.vector_score,
                        graph_score=item.provenance.graph_score,
                        confidence=item.provenance.confidence,
                        exact_contribution=item.provenance.exact_contribution,
                        source_revision=item.provenance.source_revision,
                        index_revision=item.provenance.index_revision,
                        lifecycle_eligible=item.provenance.lifecycle_eligible,
                        temporal_eligible=item.provenance.temporal_eligible,
                        title_alias_contribution=item.provenance.title_alias_contribution,
                    ),
                )
                for item in result.matches
            ],
            context_pack=result.context_pack,
            trace=_trace_response(result.trace),
        )


def _trace_response(trace: RecallTrace) -> RecallTraceResponse:
    """Map the internal trace to the strict response schema."""
    return RecallTraceResponse(
        stages=[
            RecallStageTraceResponse(
                route=item.route,
                status=item.status,
                hit_count=item.hit_count,
                project=item.project,
                effective_strategy=(
                    None
                    if item.effective_strategy is None
                    else item.effective_strategy.value
                ),
                reason=item.reason,
                warnings=list(item.warnings),
                degraded=item.degraded,
            )
            for item in trace.stages
        ],
        skipped_scopes=list(trace.skipped_scopes),
        fallback_expansion=list(trace.fallback_expansion),
        degraded_subsystems=list(trace.degraded_subsystems),
        outcome=trace.outcome,
        confidence=trace.confidence,
        search_call_count=trace.search_call_count,
    )
