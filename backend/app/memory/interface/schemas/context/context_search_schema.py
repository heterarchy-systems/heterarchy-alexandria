from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.memory.domain.event_enum.context_enums import (
    ContextGraphDirection,
    ContextGraphSignalType,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    MemoryFunction,
    RagStrategy,
)
from app.memory.domain.types.context_payload_types import ContextRetrievalSource
from app.memory.interface.schemas.context.context_schema import (
    ContextChunkResponse,
    ContextResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    exclude_none_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONValue


class ContextSearchRequest(StrictSchemaModel):
    """Payload for RAG context search."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Query for this context search request."),
    ]
    strategy: Annotated[
        RagStrategy, Field(description="Strategy for this context search request.")
    ] = RagStrategy.HYBRID
    limit: Annotated[
        int, Field(description="Limit for this context search request.", ge=1, le=50)
    ] = 5
    project: Annotated[
        str | None, Field(description="Project for this context search request.")
    ] = None
    kind: Annotated[
        ContextKind | None, Field(description="Kind for this context search request.")
    ] = None
    include_scopes: Annotated[
        list[ContextScope],
        Field(description="Include scopes for this context search request."),
    ] = schema_list_default()
    workspace_id: Annotated[
        str | None,
        Field(description="Workspace identifier for this context search request."),
    ] = None
    agent_id: Annotated[
        str | None,
        Field(description="Agent identifier for this context search request."),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description="User identifier for this context search request."),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description="Session identifier for this context search request."),
    ] = None
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        Field(
            description="Include lifecycle statuses for this context search request."
        ),
    ] = schema_list_default()
    prefer_memory_functions: Annotated[
        list[MemoryFunction],
        Field(
            description="Soft functional-memory preference in caller-provided priority order."
        ),
    ] = schema_list_default()

    @field_validator(
        "include_scopes",
        "include_lifecycle_statuses",
        "prefer_memory_functions",
        mode="before",
    )
    @classmethod
    def default_include_scopes(cls, value: JSONValue) -> JSONValue:
        """Normalize legacy null scope filters to an empty list.

        Args:
            value: Raw boundary value.

        Returns:
            Empty list for legacy nulls, otherwise the original value for
            Pydantic to validate against the typed field contract.
        """
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def validate_requested_scope_identities(self) -> ContextSearchRequest:
        """Reject explicit scope lanes whose required identity is absent.

        Returns:
            Validated search request.
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


class ContextGraphEvidenceResponse(StrictSchemaModel):
    """One graph relationship explaining optional recall evidence."""

    signal: Annotated[
        ContextGraphSignalType,
        Field(description="Signal for this context graph evidence response."),
    ]
    relation: Annotated[
        str, Field(description="Relation for this context graph evidence response.")
    ]
    direction: Annotated[
        ContextGraphDirection,
        Field(description="Direction for this context graph evidence response."),
    ]
    source_context_id: Annotated[
        str,
        Field(
            description="Source context identifier for this context graph evidence response."
        ),
    ]
    target_context_id: Annotated[
        str,
        Field(
            description="Target context identifier for this context graph evidence response."
        ),
    ]
    target_title: Annotated[
        str, Field(description="Target title for this context graph evidence response.")
    ]
    distance: Annotated[
        int, Field(description="Distance for this context graph evidence response.")
    ]
    evidence_ref: Annotated[
        str, Field(description="Evidence ref for this context graph evidence response.")
    ]


class ContextSearchMatchResponse(StrictSchemaModel):
    """One retrieved context chunk with scores."""

    context: Annotated[
        ContextResponse,
        Field(description="Context for this context search match response."),
    ]
    chunk: Annotated[
        ContextChunkResponse,
        Field(description="Chunk for this context search match response."),
    ]
    score: Annotated[
        float, Field(description="Score for this context search match response.")
    ]
    fts_score: Annotated[
        float | None,
        Field(description="FTS score for this context search match response."),
    ]
    vector_score: Annotated[
        float | None,
        Field(description="Vector score for this context search match response."),
    ]
    graph_score: Annotated[
        float | None,
        Field(
            description="Graph-aware title relevance score when AUTO graph retrieval reranks this match."
        ),
    ]
    why_retrieved: Annotated[
        str, Field(description="Why retrieved for this context search match response.")
    ]
    canonical_context_id: Annotated[
        str,
        Field(
            description="Canonical context identifier for this context search match response."
        ),
    ]
    lifecycle_status: Annotated[
        ContextRecallLifecycleStatus,
        Field(description="Lifecycle status for this context search match response."),
    ]
    source: Annotated[
        ContextRetrievalSource,
        Field(description="Source for this context search match response."),
    ]
    retrieval_strategy: Annotated[
        RagStrategy,
        Field(description="Retrieval strategy for this context search match response."),
    ]
    graph_evidence: Annotated[
        list[ContextGraphEvidenceResponse] | None,
        Field(description="Graph evidence for this context search match response."),
        exclude_none_field(),
    ] = None


class ContextPackResponse(StrictSchemaModel):
    """RAG context pack response."""

    query: Annotated[str, Field(description="Query for this context pack response.")]
    strategy: Annotated[
        RagStrategy, Field(description="Strategy for this context pack response.")
    ]
    effective_strategy: Annotated[
        RagStrategy,
        Field(description="Effective strategy for this context pack response."),
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this context pack response.")
    ]
    recall_scopes: Annotated[
        list[ContextScope],
        Field(description="Recall scopes for this context pack response."),
    ]
    matches: Annotated[
        list[ContextSearchMatchResponse],
        Field(description="Matches for this context pack response."),
    ]
    context_pack: Annotated[
        str, Field(description="Context pack for this context pack response.")
    ]
