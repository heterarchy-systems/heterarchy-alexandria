"""Context retrieval schema contracts."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.event_enum.context_enums import (
    ContextGraphDirection,
    ContextGraphSignalType,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagHealthState,
    RagStrategy,
)
from app.memory.domain.types.context_payload_types import ContextRetrievalSource
from app.memory.interface.schemas.context.context_schema import (
    ContextChunkResponse,
    ContextResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    exclude_none_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONObject, JSONValue
from pydantic import StringConstraints, field_validator, model_validator


class ContextSearchRequest(StrictSchemaModel):
    """Payload for RAG context search."""

    query: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Query for this context search request."),
    ]
    strategy: Annotated[
        RagStrategy, described_field("Strategy for this context search request.")
    ] = RagStrategy.HYBRID
    limit: Annotated[
        int, described_field("Limit for this context search request.", ge=1, le=50)
    ] = 5
    project: Annotated[
        str | None, described_field("Project for this context search request.")
    ] = None
    kind: Annotated[
        ContextKind | None, described_field("Kind for this context search request.")
    ] = None
    include_scopes: Annotated[
        list[ContextScope],
        described_field("Include scopes for this context search request."),
    ] = schema_list_default()
    workspace_id: Annotated[
        str | None,
        described_field("Workspace identifier for this context search request."),
    ] = None
    agent_id: Annotated[
        str | None, described_field("Agent identifier for this context search request.")
    ] = None
    user_id: Annotated[
        str | None, described_field("User identifier for this context search request.")
    ] = None
    session_id: Annotated[
        str | None,
        described_field("Session identifier for this context search request."),
    ] = None
    include_lifecycle_statuses: Annotated[
        list[ContextRecallLifecycleStatus],
        described_field("Include lifecycle statuses for this context search request."),
    ] = schema_list_default()

    @field_validator("include_scopes", "include_lifecycle_statuses", mode="before")
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
        described_field("Signal for this context graph evidence response."),
    ]
    relation: Annotated[
        str, described_field("Relation for this context graph evidence response.")
    ]
    direction: Annotated[
        ContextGraphDirection,
        described_field("Direction for this context graph evidence response."),
    ]
    source_context_id: Annotated[
        str,
        described_field(
            "Source context identifier for this context graph evidence response."
        ),
    ]
    target_context_id: Annotated[
        str,
        described_field(
            "Target context identifier for this context graph evidence response."
        ),
    ]
    target_title: Annotated[
        str, described_field("Target title for this context graph evidence response.")
    ]
    distance: Annotated[
        int, described_field("Distance for this context graph evidence response.")
    ]
    evidence_ref: Annotated[
        str, described_field("Evidence ref for this context graph evidence response.")
    ]


class ContextSearchMatchResponse(StrictSchemaModel):
    """One retrieved context chunk with scores."""

    context: Annotated[
        ContextResponse,
        described_field("Context for this context search match response."),
    ]
    chunk: Annotated[
        ContextChunkResponse,
        described_field("Chunk for this context search match response."),
    ]
    score: Annotated[
        float, described_field("Score for this context search match response.")
    ]
    fts_score: Annotated[
        float | None,
        described_field("FTS score for this context search match response."),
    ]
    vector_score: Annotated[
        float | None,
        described_field("Vector score for this context search match response."),
    ]
    why_retrieved: Annotated[
        str, described_field("Why retrieved for this context search match response.")
    ]
    canonical_context_id: Annotated[
        str,
        described_field(
            "Canonical context identifier for this context search match response."
        ),
    ]
    lifecycle_status: Annotated[
        ContextRecallLifecycleStatus,
        described_field("Lifecycle status for this context search match response."),
    ]
    source: Annotated[
        ContextRetrievalSource,
        described_field("Source for this context search match response."),
    ]
    retrieval_strategy: Annotated[
        RagStrategy,
        described_field("Retrieval strategy for this context search match response."),
    ]
    graph_evidence: Annotated[
        list[ContextGraphEvidenceResponse] | None,
        described_field("Graph evidence for this context search match response."),
        exclude_none_field(),
    ] = None


class ContextPackResponse(StrictSchemaModel):
    """RAG context pack response."""

    query: Annotated[str, described_field("Query for this context pack response.")]
    strategy: Annotated[
        RagStrategy, described_field("Strategy for this context pack response.")
    ]
    effective_strategy: Annotated[
        RagStrategy,
        described_field("Effective strategy for this context pack response."),
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this context pack response.")
    ]
    recall_scopes: Annotated[
        list[ContextScope],
        described_field("Recall scopes for this context pack response."),
    ]
    matches: Annotated[
        list[ContextSearchMatchResponse],
        described_field("Matches for this context pack response."),
    ]
    context_pack: Annotated[
        str, described_field("Context pack for this context pack response.")
    ]


class ContextEmbeddingSourceStatusResponse(StrictSchemaModel):
    """Source-level embedding fingerprint diagnostics."""

    source_name: Annotated[
        str,
        described_field(
            "Source name for this context embedding source status response."
        ),
    ]
    status: Annotated[
        RagHealthState,
        described_field("Status for this context embedding source status response."),
    ]
    total_rows: Annotated[
        int,
        described_field(
            "Total rows for this context embedding source status response."
        ),
    ]
    current_rows: Annotated[
        int,
        described_field(
            "Current rows for this context embedding source status response."
        ),
    ]
    stale_rows: Annotated[
        int,
        described_field(
            "Stale rows for this context embedding source status response."
        ),
    ]
    missing_rows: Annotated[
        int,
        described_field(
            "Missing rows for this context embedding source status response."
        ),
    ]
    current_fingerprint: Annotated[
        JSONObject,
        described_field(
            "Current fingerprint for this context embedding source status response."
        ),
    ]
    stored_fingerprints: Annotated[
        list[JSONObject],
        described_field(
            "Stored fingerprints for this context embedding source status response."
        ),
    ]


class RagStatusResponse(StrictSchemaModel):
    """Context RAG health response."""

    fts: Annotated[RagHealthState, described_field("FTS for this RAG status response.")]
    vector: Annotated[
        RagHealthState, described_field("Vector for this RAG status response.")
    ]
    embedding: Annotated[
        RagHealthState, described_field("Embedding for this RAG status response.")
    ]
    default_strategy: Annotated[
        RagStrategy, described_field("Default strategy for this RAG status response.")
    ]
    model_name: Annotated[
        str, described_field("Model name for this RAG status response.")
    ]
    dimensions: Annotated[
        int, described_field("Dimensions for this RAG status response.")
    ]
    fingerprint: Annotated[
        JSONObject | None, described_field("Fingerprint for this RAG status response.")
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this RAG status response.")
    ]
    source_statuses: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        described_field("Source statuses for this RAG status response."),
    ] = schema_list_default()


class ContextReindexResponse(StrictSchemaModel):
    """Context embedding reindex response."""

    scanned: Annotated[
        int, described_field("Scanned for this context reindex response.")
    ]
    updated: Annotated[
        int, described_field("Updated for this context reindex response.")
    ]
    skipped: Annotated[
        int, described_field("Skipped for this context reindex response.")
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this context reindex response.")
    ]


class ContextSoftRebuildResponse(StrictSchemaModel):
    """Context embedding/vector soft rebuild response."""

    mode: Annotated[
        str, described_field("Mode for this context soft rebuild response.")
    ]
    source_preservation: Annotated[
        str,
        described_field("Source preservation for this context soft rebuild response."),
    ]
    hard_delete_performed: Annotated[
        bool,
        described_field(
            "Hard delete performed for this context soft rebuild response."
        ),
    ]
    before: Annotated[
        RagStatusResponse,
        described_field("Before for this context soft rebuild response."),
    ]
    source_status_before: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        described_field("Source status before for this context soft rebuild response."),
    ]
    reindex: Annotated[
        ContextReindexResponse,
        described_field("Reindex for this context soft rebuild response."),
    ]
    after: Annotated[
        RagStatusResponse,
        described_field("After for this context soft rebuild response."),
    ]
    source_status_after: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        described_field("Source status after for this context soft rebuild response."),
    ]
    verification_query: Annotated[
        str | None,
        described_field("Verification query for this context soft rebuild response."),
    ]
    verification_matches: Annotated[
        int,
        described_field("Verification matches for this context soft rebuild response."),
    ]
    verification_context_ids: Annotated[
        list[str],
        described_field(
            "Verification context identifiers for this context soft rebuild response."
        ),
    ]
    verification_warnings: Annotated[
        list[str],
        described_field(
            "Verification warnings for this context soft rebuild response."
        ),
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this context soft rebuild response.")
    ]
