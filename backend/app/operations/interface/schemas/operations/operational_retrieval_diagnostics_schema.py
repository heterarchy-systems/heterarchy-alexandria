"""Strict HTTP contracts for operator-only Context retrieval diagnostics."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator, model_validator

from app.memory.application.contexts.diagnostics.context_search_trace import (
    ContextSearchExecutionTrace,
    ContextSearchExplainResult,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    MemoryFunction,
    RagStrategy,
)
from app.operations.application.diagnostics.operational_retrieval_diagnostics_service import (
    OperationalRetrievalDiagnosticsQuery,
)
from app.operations.interface.schemas.operations.operational_retrieval_execution_trace_schema import (
    OperationalRetrievalFusionTraceResponse,
    OperationalRetrievalTimingTraceResponse,
)
from app.operations.interface.schemas.operations.operational_retrieval_plan_schema import (
    OperationalRetrievalPlanResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import enum_value


class OperationalRetrievalExplainRequest(StrictSchemaModel):
    """Bounded operator request for one retrieval flight-recorder execution."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=10_000),
        described_field("Query to execute through the normal Context retrieval path."),
    ]
    strategy: Annotated[
        RagStrategy,
        described_field("Retrieval strategy requested for this diagnostic execution."),
    ] = RagStrategy.HYBRID
    limit: Annotated[
        int,
        described_field("Maximum final Context matches.", ge=1, le=50),
    ] = 5
    project: Annotated[
        str | None,
        described_field("Optional project recall filter."),
    ] = None
    kind: Annotated[
        ContextKind | None,
        described_field("Optional Context kind recall filter."),
    ] = None
    include_scopes: Annotated[
        list[ContextScope],
        described_field(
            "Explicit recall scopes; empty selects normal Context defaults."
        ),
    ] = schema_list_default()
    workspace_id: Annotated[
        str | None,
        described_field("Optional workspace identity for scoped recall."),
    ] = None
    agent_id: Annotated[
        str | None,
        described_field("Optional agent identity for scoped recall."),
    ] = None
    user_id: Annotated[
        str | None,
        described_field("Optional user identity for scoped recall."),
    ] = None
    session_id: Annotated[
        str | None,
        described_field("Optional session identity for scoped recall."),
    ] = None
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        described_field("Optional administrative lifecycle filters."),
    ] = schema_list_default()
    prefer_memory_functions: Annotated[
        list[MemoryFunction],
        described_field("Optional soft functional-memory preference order."),
    ] = schema_list_default()

    @field_validator(
        "include_scopes",
        "include_lifecycle_statuses",
        "prefer_memory_functions",
        mode="before",
    )
    @classmethod
    def normalize_null_lists(cls, value: JSONValue) -> JSONValue:
        """Normalize legacy null list filters to empty typed lists.

        Args:
            value: Raw boundary value.

        Returns:
            Empty list for null input; otherwise the original boundary value.
        """
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def validate_requested_scope_identities(self) -> OperationalRetrievalExplainRequest:
        """Reject explicit scopes that omit their required identity.

        Returns:
            Validated operator diagnostics request.
        """
        requirements = (
            (ContextScope.PROJECT, self.project, "MISSING_PROJECT"),
            (ContextScope.AGENT, self.agent_id, "MISSING_AGENT_ID"),
            (ContextScope.USER, self.user_id, "MISSING_USER_ID"),
            (ContextScope.SESSION, self.session_id, "MISSING_SESSION_ID"),
        )
        missing = [
            field_name
            for scope, identity, field_name in requirements
            if scope in self.include_scopes
            and (identity is None or not identity.strip())
        ]
        if missing:
            raise ValueError("scope identity is required: " + ", ".join(missing))
        return self

    def to_query(self) -> OperationalRetrievalDiagnosticsQuery:
        """Map the strict HTTP request into the application command.

        Returns:
            Immutable application diagnostics query.
        """
        return OperationalRetrievalDiagnosticsQuery(
            query=self.query,
            strategy=enum_value(self.strategy, RagStrategy, "strategy"),
            limit=self.limit,
            project=self.project,
            kind=(
                None
                if self.kind is None
                else enum_value(self.kind, ContextKind, "kind")
            ),
            include_scopes=tuple(
                enum_value(scope, ContextScope, "include_scopes")
                for scope in self.include_scopes
            ),
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            user_id=self.user_id,
            session_id=self.session_id,
            include_lifecycle_statuses=tuple(
                enum_value(
                    lifecycle_status,
                    ContextRecallLifecycleStatus,
                    "include_lifecycle_statuses",
                )
                for lifecycle_status in self.include_lifecycle_statuses
            ),
            prefer_memory_functions=tuple(
                enum_value(
                    memory_function,
                    MemoryFunction,
                    "prefer_memory_functions",
                )
                for memory_function in self.prefer_memory_functions
            ),
        )


class OperationalRetrievalMatchResponse(StrictSchemaModel):
    """Bounded retrieval result metadata without Context body or embedding payloads."""

    context_id: Annotated[str, described_field("Retrieved Context identifier.")]
    title: Annotated[str, described_field("Retrieved Context title.")]
    score: Annotated[float, described_field("Final retrieval score.")]
    fts_score: Annotated[
        float | None,
        described_field("FTS lane score when lexical evidence exists."),
    ] = None
    vector_score: Annotated[
        float | None,
        described_field("Vector lane score when semantic evidence exists."),
    ] = None
    graph_score: Annotated[
        float | None,
        described_field(
            "AUTO graph-aware title relevance score when graph reranking applies."
        ),
    ] = None
    graph_evidence_count: Annotated[
        int,
        described_field("Number of score-preserving graph evidence entries.", ge=0),
    ]


class OperationalRetrievalExecutionTraceResponse(StrictSchemaModel):
    """Bounded Python orchestration and Rust fusion execution diagnostics."""

    requested_strategy: Annotated[
        RagStrategy, described_field("Retrieval strategy requested by the operator.")
    ]
    effective_strategy: Annotated[
        RagStrategy, described_field("Strategy actually executed after health checks.")
    ]
    requested_limit: Annotated[
        int, described_field("Requested final result limit.", ge=1)
    ]
    hybrid_candidate_limit: Annotated[
        int | None,
        described_field("Hybrid over-fetch budget when Hybrid fusion executed.", ge=1),
    ] = None
    fts_source_calls: Annotated[
        int, described_field("FTS source calls executed.", ge=0)
    ]
    fts_query_variants_attempted: Annotated[
        int, described_field("Deterministic FTS query variants attempted.", ge=0)
    ]
    fts_source_candidate_count: Annotated[
        int, described_field("Raw FTS source candidates observed.", ge=0)
    ]
    fts_ranked_candidate_count: Annotated[
        int, described_field("FTS candidates retained after lane ranking.", ge=0)
    ]
    vector_candidate_count: Annotated[
        int, described_field("Vector candidates observed.", ge=0)
    ]
    post_fusion_match_count: Annotated[
        int,
        described_field("Matches after strategy execution and optional fusion.", ge=0),
    ]
    filtered_match_count: Annotated[
        int, described_field("Matches after scope filtering.", ge=0)
    ]
    graph_evidence_match_count: Annotated[
        int, described_field("Matches carrying graph evidence.", ge=0)
    ]
    graph_enrichment_applied: Annotated[
        bool, described_field("Whether score-preserving graph enrichment was applied.")
    ]
    graph_enrichment_degraded: Annotated[
        bool, described_field("Whether graph enrichment degraded or was rejected.")
    ]
    graph_expansion_discovered_candidate_count: Annotated[
        int,
        described_field(
            "Distinct non-primary nodes reached by bounded traversal.", ge=0
        ),
    ]
    graph_expansion_selected_candidate_count: Annotated[
        int, described_field("Rust-selected graph candidates before hydration.", ge=0)
    ]
    graph_expansion_hydrated_candidate_count: Annotated[
        int,
        described_field(
            "Selected graph candidates hydrated from canonical storage.", ge=0
        ),
    ]
    graph_expansion_filtered_candidate_count: Annotated[
        int,
        described_field(
            "Selected graph candidates rejected during hydration/policy.", ge=0
        ),
    ]
    graph_expansion_appended_candidate_count: Annotated[
        int,
        described_field(
            "Graph-only candidates retained in the final bounded result.", ge=0
        ),
    ]
    graph_expansion_applied: Annotated[
        bool,
        described_field("Whether graph expansion retained at least one new candidate."),
    ]
    graph_expansion_degraded: Annotated[
        bool,
        described_field("Whether graph expansion failed and preserved primary recall."),
    ]
    kernel_fusion: Annotated[
        OperationalRetrievalFusionTraceResponse | None,
        described_field("Rust hybrid-fusion diagnostics when fusion executed."),
    ] = None
    retrieval_plan: Annotated[
        OperationalRetrievalPlanResponse | None,
        described_field("AUTO planner metadata when adaptive planning executed."),
    ] = None
    timings: Annotated[
        OperationalRetrievalTimingTraceResponse,
        described_field("Explain-only stage timings."),
    ]

    @classmethod
    def from_entity(
        cls,
        trace: ContextSearchExecutionTrace,
    ) -> OperationalRetrievalExecutionTraceResponse:
        """Map application execution diagnostics to the strict HTTP contract.

        Args:
            trace: Bounded search execution trace.

        Returns:
            Strict retrieval execution trace response.
        """
        return cls(
            requested_strategy=trace.requested_strategy,
            effective_strategy=trace.effective_strategy,
            requested_limit=trace.requested_limit,
            hybrid_candidate_limit=trace.hybrid_candidate_limit,
            fts_source_calls=trace.fts_source_calls,
            fts_query_variants_attempted=trace.fts_query_variants_attempted,
            fts_source_candidate_count=trace.fts_source_candidate_count,
            fts_ranked_candidate_count=trace.fts_ranked_candidate_count,
            vector_candidate_count=trace.vector_candidate_count,
            post_fusion_match_count=trace.post_fusion_match_count,
            filtered_match_count=trace.filtered_match_count,
            graph_evidence_match_count=trace.graph_evidence_match_count,
            graph_enrichment_applied=trace.graph_enrichment_applied,
            graph_enrichment_degraded=trace.graph_enrichment_degraded,
            graph_expansion_discovered_candidate_count=(
                trace.graph_expansion_discovered_candidate_count
            ),
            graph_expansion_selected_candidate_count=(
                trace.graph_expansion_selected_candidate_count
            ),
            graph_expansion_hydrated_candidate_count=(
                trace.graph_expansion_hydrated_candidate_count
            ),
            graph_expansion_filtered_candidate_count=(
                trace.graph_expansion_filtered_candidate_count
            ),
            graph_expansion_appended_candidate_count=(
                trace.graph_expansion_appended_candidate_count
            ),
            graph_expansion_applied=trace.graph_expansion_applied,
            graph_expansion_degraded=trace.graph_expansion_degraded,
            kernel_fusion=(
                None
                if trace.kernel_fusion is None
                else OperationalRetrievalFusionTraceResponse.from_entity(
                    trace.kernel_fusion
                )
            ),
            retrieval_plan=(
                None
                if trace.retrieval_plan is None
                else OperationalRetrievalPlanResponse.from_entity(trace.retrieval_plan)
            ),
            timings=OperationalRetrievalTimingTraceResponse.from_entity(trace.timings),
        )


class OperationalRetrievalExplainResponse(StrictSchemaModel):
    """Operator diagnostics response that intentionally excludes Context bodies."""

    query: Annotated[str, described_field("Executed Context query.")]
    strategy: Annotated[RagStrategy, described_field("Requested retrieval strategy.")]
    effective_strategy: Annotated[
        RagStrategy, described_field("Effective retrieval strategy.")
    ]
    warnings: Annotated[
        list[str], described_field("Warnings emitted by the normal retrieval path.")
    ] = schema_list_default()
    recall_scopes: Annotated[
        list[ContextScope], described_field("Recall scopes used by Context search.")
    ] = schema_list_default()
    match_count: Annotated[int, described_field("Number of returned matches.", ge=0)]
    context_pack_built: Annotated[
        bool, described_field("Whether normal Context Pack rendering completed.")
    ]
    matches: Annotated[
        list[OperationalRetrievalMatchResponse],
        described_field(
            "Bounded result metadata; Context bodies are intentionally omitted."
        ),
    ] = schema_list_default()
    trace: Annotated[
        OperationalRetrievalExecutionTraceResponse,
        described_field("Python orchestration and Rust fusion diagnostics."),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ContextSearchExplainResult,
    ) -> OperationalRetrievalExplainResponse:
        """Map an explained Context search into the bounded operator response.

        Args:
            result: Normal Context pack paired with execution diagnostics.

        Returns:
            Strict operator response without raw Context body or embedding data.
        """
        pack = result.pack
        return cls(
            query=pack.query,
            strategy=pack.strategy,
            effective_strategy=pack.effective_strategy,
            warnings=list(pack.warnings),
            recall_scopes=list(pack.recall_scopes),
            match_count=len(pack.matches),
            context_pack_built=bool(pack.context_pack.strip()),
            matches=[
                OperationalRetrievalMatchResponse(
                    context_id=match.context.id,
                    title=match.context.title,
                    score=match.score,
                    fts_score=match.fts_score,
                    vector_score=match.vector_score,
                    graph_score=match.graph_score,
                    graph_evidence_count=len(match.graph_evidence or ()),
                )
                for match in pack.matches
            ],
            trace=OperationalRetrievalExecutionTraceResponse.from_entity(result.trace),
        )
