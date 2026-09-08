"""Pydantic HTTP and MCP contracts for high-level memory recall."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator, model_validator

from app.memory.domain.contracts.recall_contracts import (
    RecallExactSelector,
    RecallRequest,
)
from app.memory.domain.entities.recall import RecallResult, RecallTrace
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
)
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
    RecallStageStatus,
)
from app.memory.interface.schemas.context.context_mapping import match_payload
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextSearchMatchResponse,
)
from app.obsidian.interface.schemas.obsidian.obsidian_logical_identity_schema import (
    ObsidianLogicalIdentitySchema,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    exclude_none_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import enum_value


class RecallExactSelectorRequest(StrictSchemaModel):
    """Optional source selector evaluated before retrieval-index search."""

    note_id: Annotated[
        str | None,
        described_field("Canonical note identifier for exact recall.", max_length=512),
        exclude_none_field(),
    ] = None
    path: Annotated[
        str | None,
        described_field(
            "Canonical vault-relative path for exact recall.", max_length=2048
        ),
        exclude_none_field(),
    ] = None
    logical_identity: Annotated[
        ObsidianLogicalIdentitySchema | None,
        described_field("Logical report identity for exact recall."),
        exclude_none_field(),
    ] = None

    @field_validator("note_id", "path")
    @classmethod
    def normalize_selector_text(cls, value: str | None) -> str | None:
        """Normalize optional exact selector text."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_selector(self) -> RecallExactSelectorRequest:
        """Require one concrete exact selector."""
        selected = sum(
            (
                self.note_id is not None,
                self.path is not None,
                self.logical_identity is not None,
            )
        )
        if selected != 1:
            raise ValueError(
                "exact_selector requires exactly one of note_id, path, or logical_identity"
            )
        return self

    def to_contract(self) -> RecallExactSelector:
        """Convert the boundary selector into its typed domain contract."""
        return RecallExactSelector(
            note_id=self.note_id,
            path=self.path,
            logical_identity=(
                None
                if self.logical_identity is None
                else self.logical_identity.to_identity()
            ),
        )


class RecallRequestSchema(StrictSchemaModel):
    """High-level recall request with AUTO and STRICT scope modes."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=10000),
        described_field("Natural-language query for high-level recall."),
    ]
    limit: Annotated[
        int,
        described_field("Maximum recalled contexts.", ge=1, le=50),
    ] = 5
    scope_mode: Annotated[
        RecallScopeMode,
        described_field("Scope identity resolution mode for high-level recall."),
    ] = RecallScopeMode.AUTO
    include_scopes: Annotated[
        list[ContextScope],
        described_field("Optional explicit scope lanes for STRICT recall."),
    ] = schema_list_default()
    project: Annotated[
        str | None,
        described_field("Primary project identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    workspace_id: Annotated[
        str | None,
        described_field("Workspace identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    agent_id: Annotated[
        str | None,
        described_field("Agent identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    session_id: Annotated[
        str | None,
        described_field("Session identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    user_id: Annotated[
        str | None,
        described_field("User identity for recall.", max_length=512),
        exclude_none_field(),
    ] = None
    related_projects: Annotated[
        list[str],
        described_field("Bounded related project expansion inputs.", max_length=4),
    ] = schema_list_default()
    exact_selector: Annotated[
        RecallExactSelectorRequest | None,
        described_field("Optional exact canonical selector."),
        exclude_none_field(),
    ] = None
    as_of: Annotated[
        AwareTimestamp | None,
        described_field("Historical instant for temporal recall."),
        exclude_none_field(),
    ] = None
    kind: Annotated[
        ContextKind | None,
        described_field("Optional Context kind filter."),
        exclude_none_field(),
    ] = None
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        described_field("Optional lifecycle eligibility filter."),
    ] = schema_list_default()

    @field_validator(
        "include_scopes",
        "include_lifecycle_statuses",
        mode="before",
    )
    @classmethod
    def normalize_optional_lists(cls, value: JSONValue) -> JSONValue:
        """Normalize omitted/null optional enum lists to empty lists."""
        return [] if value is None else value

    @field_validator(
        "query", "project", "workspace_id", "agent_id", "session_id", "user_id"
    )
    @classmethod
    def normalize_identity_text(cls, value: str | None) -> str | None:
        """Normalize request query and optional identity text."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("related_projects")
    @classmethod
    def normalize_related_projects(cls, value: list[str]) -> list[str]:
        """Normalize and bound related-project expansion inputs."""
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) > 4:
            raise ValueError("related_projects must contain at most 4 projects")
        return normalized

    def to_contract(self) -> RecallRequest:
        """Convert the external schema into the internal typed request."""
        return RecallRequest(
            query=self.query,
            limit=self.limit,
            scope_mode=enum_value(self.scope_mode, RecallScopeMode, "scope_mode"),
            include_scopes=tuple(
                enum_value(item, ContextScope, "include_scopes")
                for item in self.include_scopes
            ),
            project=self.project,
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
            user_id=self.user_id,
            related_projects=tuple(self.related_projects),
            selector=(
                None
                if self.exact_selector is None
                else self.exact_selector.to_contract()
            ),
            as_of=self.as_of,
            kind=(
                None
                if self.kind is None
                else enum_value(self.kind, ContextKind, "kind")
            ),
            include_lifecycle_statuses=tuple(
                enum_value(
                    item,
                    ContextRecallLifecycleStatus,
                    "include_lifecycle_statuses",
                )
                for item in self.include_lifecycle_statuses
            ),
        )


class RecallProvenanceResponse(StrictSchemaModel):
    """Bounded evidence explaining one high-level recall match."""

    route: Annotated[RecallRoute, described_field("Recall route used for the match.")]
    project_affinity: Annotated[
        RecallProjectAffinity,
        described_field("Primary, related, or global project affinity."),
    ]
    canonical_context_id: Annotated[
        str,
        described_field("Canonical Context identifier."),
    ]
    authority: Annotated[
        str,
        described_field("Declared memory authority or UNKNOWN."),
    ]
    chunk_id: Annotated[str, described_field("Matched chunk identifier.")]
    heading: Annotated[
        str | None,
        described_field("Matched heading when available."),
        exclude_none_field(),
    ]
    project: Annotated[
        str | None,
        described_field("Matched project when available."),
        exclude_none_field(),
    ]
    fts_score: Annotated[
        float | None,
        described_field("Existing FTS contribution when available."),
        exclude_none_field(),
    ]
    vector_score: Annotated[
        float | None,
        described_field("Existing vector contribution when available."),
        exclude_none_field(),
    ]
    graph_score: Annotated[
        float | None,
        described_field("Existing graph contribution when available."),
        exclude_none_field(),
    ]
    confidence: Annotated[float, described_field("Bounded evidence confidence.")]
    exact_contribution: Annotated[
        str | None,
        described_field("Exact selector contribution when used."),
        exclude_none_field(),
    ]
    source_revision: Annotated[
        str | None,
        described_field("Source revision when the source supplied one."),
        exclude_none_field(),
    ]
    index_revision: Annotated[
        str | None,
        described_field("Index revision when the source supplied one."),
        exclude_none_field(),
    ]
    lifecycle_eligible: Annotated[
        bool, described_field("Whether lifecycle eligibility was satisfied.")
    ]
    temporal_eligible: Annotated[
        bool | None,
        described_field("Temporal eligibility when evaluated."),
        exclude_none_field(),
    ]
    title_alias_contribution: Annotated[
        str | None,
        described_field("Title or alias contribution when available."),
        exclude_none_field(),
    ] = None


class RecallMatchResponse(StrictSchemaModel):
    """One existing Context match with high-level provenance."""

    match: Annotated[
        ContextSearchMatchResponse,
        described_field("Existing Context search match."),
    ]
    provenance: Annotated[
        RecallProvenanceResponse,
        described_field("Bounded recall provenance."),
    ]


class RecallStageTraceResponse(StrictSchemaModel):
    """One attempted or skipped high-level recall stage."""

    route: Annotated[RecallRoute, described_field("Recall stage route.")]
    status: Annotated[RecallStageStatus, described_field("Recall stage status.")]
    hit_count: Annotated[int, described_field("Number of stage hits.", ge=0)]
    project: Annotated[
        str | None,
        described_field("Project used by the stage."),
        exclude_none_field(),
    ]
    effective_strategy: Annotated[
        str | None,
        described_field("Existing effective retrieval strategy."),
        exclude_none_field(),
    ]
    reason: Annotated[
        str | None,
        described_field("Bounded stage reason."),
        exclude_none_field(),
    ]
    warnings: Annotated[list[str], described_field("Stage warnings.")]
    degraded: Annotated[bool, described_field("Whether the stage degraded.")]


class RecallTraceResponse(StrictSchemaModel):
    """Compact route and fallback trace for high-level recall."""

    stages: Annotated[
        list[RecallStageTraceResponse], described_field("Recall stage trace.")
    ]
    skipped_scopes: Annotated[
        list[str], described_field("Unavailable AUTO scope lanes skipped.")
    ]
    fallback_expansion: Annotated[
        list[RecallRoute], described_field("Fallback routes that were attempted.")
    ]
    degraded_subsystems: Annotated[
        list[str], described_field("Degraded subsystem identifiers.")
    ]
    outcome: Annotated[RecallOutcome, described_field("Bounded recall outcome.")]
    confidence: Annotated[float, described_field("Highest returned confidence.")]
    search_call_count: Annotated[
        int, described_field("Number of existing search authority calls.", ge=0)
    ]


class RecallResponseSchema(StrictSchemaModel):
    """Agent-facing high-level recall response."""

    query: Annotated[str, described_field("Normalized recall query.")]
    scope_mode: Annotated[
        RecallScopeMode, described_field("Scope resolution mode used.")
    ]
    recall_scopes: Annotated[
        list[ContextScope], described_field("Effective recall scope lanes.")
    ]
    effective_strategy: Annotated[
        str, described_field("Last effective retrieval strategy used.")
    ]
    outcome: Annotated[RecallOutcome, described_field("Bounded recall outcome.")]
    warnings: Annotated[list[str], described_field("Recall warnings.")]
    matches: Annotated[
        list[RecallMatchResponse], described_field("Recalled Context matches.")
    ]
    context_pack: Annotated[str, described_field("Rendered bounded Context Pack.")]
    trace: Annotated[RecallTraceResponse, described_field("Compact recall trace.")]

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
