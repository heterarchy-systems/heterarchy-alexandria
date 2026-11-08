from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.types.extra_types import JSONObject


class ContextEmbeddingSourceStatusResponse(StrictSchemaModel):
    """Source-level embedding fingerprint diagnostics."""

    source_name: Annotated[
        str,
        Field(
            description="Source name for this context embedding source status response."
        ),
    ]
    status: Annotated[
        RagHealthState,
        Field(description="Status for this context embedding source status response."),
    ]
    total_rows: Annotated[
        int,
        Field(
            description="Total rows for this context embedding source status response."
        ),
    ]
    current_rows: Annotated[
        int,
        Field(
            description="Current rows for this context embedding source status response."
        ),
    ]
    stale_rows: Annotated[
        int,
        Field(
            description="Stale rows for this context embedding source status response."
        ),
    ]
    missing_rows: Annotated[
        int,
        Field(
            description="Missing rows for this context embedding source status response."
        ),
    ]
    current_fingerprint: Annotated[
        JSONObject,
        Field(
            description="Current fingerprint for this context embedding source status response."
        ),
    ]
    stored_fingerprints: Annotated[
        list[JSONObject],
        Field(
            description="Stored fingerprints for this context embedding source status response."
        ),
    ]


class RagStatusResponse(StrictSchemaModel):
    """Context RAG health response."""

    fts: Annotated[
        RagHealthState, Field(description="FTS for this RAG status response.")
    ]
    vector: Annotated[
        RagHealthState, Field(description="Vector for this RAG status response.")
    ]
    embedding: Annotated[
        RagHealthState, Field(description="Embedding for this RAG status response.")
    ]
    default_strategy: Annotated[
        RagStrategy, Field(description="Default strategy for this RAG status response.")
    ]
    model_name: Annotated[
        str, Field(description="Model name for this RAG status response.")
    ]
    dimensions: Annotated[
        int, Field(description="Dimensions for this RAG status response.")
    ]
    fingerprint: Annotated[
        JSONObject | None,
        Field(description="Fingerprint for this RAG status response."),
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this RAG status response.")
    ]
    source_statuses: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        Field(description="Source statuses for this RAG status response."),
    ] = schema_list_default()


class ContextReindexResponse(StrictSchemaModel):
    """Context embedding reindex response."""

    scanned: Annotated[
        int, Field(description="Scanned for this context reindex response.")
    ]
    updated: Annotated[
        int, Field(description="Updated for this context reindex response.")
    ]
    skipped: Annotated[
        int, Field(description="Skipped for this context reindex response.")
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this context reindex response.")
    ]


class ContextSoftRebuildResponse(StrictSchemaModel):
    """Context embedding/vector soft rebuild response."""

    mode: Annotated[
        str, Field(description="Mode for this context soft rebuild response.")
    ]
    source_preservation: Annotated[
        str,
        Field(
            description="Source preservation for this context soft rebuild response."
        ),
    ]
    hard_delete_performed: Annotated[
        bool,
        Field(
            description="Hard delete performed for this context soft rebuild response."
        ),
    ]
    before: Annotated[
        RagStatusResponse,
        Field(description="Before for this context soft rebuild response."),
    ]
    source_status_before: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        Field(
            description="Source status before for this context soft rebuild response."
        ),
    ]
    reindex: Annotated[
        ContextReindexResponse,
        Field(description="Reindex for this context soft rebuild response."),
    ]
    after: Annotated[
        RagStatusResponse,
        Field(description="After for this context soft rebuild response."),
    ]
    source_status_after: Annotated[
        list[ContextEmbeddingSourceStatusResponse],
        Field(
            description="Source status after for this context soft rebuild response."
        ),
    ]
    verification_query: Annotated[
        str | None,
        Field(description="Verification query for this context soft rebuild response."),
    ]
    verification_matches: Annotated[
        int,
        Field(
            description="Verification matches for this context soft rebuild response."
        ),
    ]
    verification_context_ids: Annotated[
        list[str],
        Field(
            description="Verification context identifiers for this context soft rebuild response."
        ),
    ]
    verification_warnings: Annotated[
        list[str],
        Field(
            description="Verification warnings for this context soft rebuild response."
        ),
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this context soft rebuild response.")
    ]
