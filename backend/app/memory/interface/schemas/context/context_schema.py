"""Context Vault request and response schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    MemoryFunction,
)
from app.shared.schemas.common_schemas import StrictRootSchemaModel, StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject


class ContextProvenanceResponse(StrictSchemaModel):
    """Generalized Context origin and evidence references."""

    source_actor_id: Annotated[
        str | None,
        Field(
            description="Source actor identifier for this context provenance response."
        ),
    ]
    source_actor_type: Annotated[
        ContextSourceType | None,
        Field(description="Source actor type for this context provenance response."),
    ]
    source_run_id: Annotated[
        str | None,
        Field(
            description="Source run identifier for this context provenance response."
        ),
    ]
    external_run_id: Annotated[
        str | None,
        Field(
            description="External run identifier for this context provenance response."
        ),
    ]
    artifact_refs: Annotated[
        list[str],
        Field(description="Artifact refs for this context provenance response."),
    ]
    evidence_refs: Annotated[
        list[str],
        Field(description="Evidence refs for this context provenance response."),
    ]
    confidence: Annotated[
        ContextImportance | None,
        Field(description="Confidence for this context provenance response."),
    ]


class ContextLifecycleResponse(StrictSchemaModel):
    """Context lifecycle, integrity, and supersede metadata."""

    status: Annotated[
        ContextRecallLifecycleStatus,
        Field(description="Status for this context lifecycle response."),
    ]
    content_hash: Annotated[
        str | None,
        Field(description="Content hash for this context lifecycle response."),
    ]
    version: Annotated[
        int | None, Field(description="Version for this context lifecycle response.")
    ]
    supersedes_context_id: Annotated[
        str | None,
        Field(
            description="Supersedes context identifier for this context lifecycle response."
        ),
    ]
    superseded_by_context_id: Annotated[
        str | None,
        Field(
            description="Superseded by context identifier for this context lifecycle response."
        ),
    ]


class ContextResponse(StrictSchemaModel):
    """Stored context response."""

    id: Annotated[
        str, Field(description="Stable identifier for this context response.")
    ]
    canonical_context_id: Annotated[
        str,
        Field(description="Canonical context identifier for this context response."),
    ]
    kind: Annotated[ContextKind, Field(description="Kind for this context response.")]
    memory_function: Annotated[
        MemoryFunction | None,
        Field(description="Functional memory role for this context response."),
    ]
    title: Annotated[str, Field(description="Title for this context response.")]
    summary: Annotated[str, Field(description="Summary for this context response.")]
    content: Annotated[str, Field(description="Content for this context response.")]
    content_format: Annotated[
        ContextContentFormat,
        Field(description="Content format for this context response."),
    ]
    project: Annotated[
        str | None, Field(description="Project for this context response.")
    ]
    scope: Annotated[
        ContextScope, Field(description="Scope for this context response.")
    ]
    workspace_id: Annotated[
        str | None, Field(description="Workspace identifier for this context response.")
    ]
    agent_id: Annotated[
        str | None, Field(description="Agent identifier for this context response.")
    ]
    user_id: Annotated[
        str | None, Field(description="User identifier for this context response.")
    ]
    session_id: Annotated[
        str | None, Field(description="Session identifier for this context response.")
    ]
    visibility: Annotated[
        ContextScope, Field(description="Visibility for this context response.")
    ]
    source_agent: Annotated[
        str, Field(description="Source agent for this context response.")
    ]
    source_type: Annotated[
        ContextSourceType, Field(description="Source type for this context response.")
    ]
    importance: Annotated[
        ContextImportance, Field(description="Importance for this context response.")
    ]
    tags: Annotated[list[str], Field(description="Tags for this context response.")]
    status: Annotated[
        ContextStorageStatus, Field(description="Status for this context response.")
    ]
    lifecycle_status: Annotated[
        ContextRecallLifecycleStatus,
        Field(description="Lifecycle status for this context response."),
    ]
    provenance: Annotated[
        ContextProvenanceResponse,
        Field(description="Provenance for this context response."),
    ]
    lifecycle: Annotated[
        ContextLifecycleResponse,
        Field(description="Lifecycle for this context response."),
    ]
    quality_score: Annotated[
        int, Field(description="Quality score for this context response.")
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this context response.")
    ]
    restore_prompt: Annotated[
        str | None, Field(description="Restore prompt for this context response.")
    ]
    metadata: Annotated[
        JSONObject, Field(description="Metadata for this context response.")
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(description="Creation timestamp for this context response."),
    ]
    updated_at: Annotated[
        AwareTimestamp,
        Field(description="Last-update timestamp for this context response."),
    ]
    last_accessed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Last accessed at for this context response."),
    ]
    expires_at: Annotated[
        AwareTimestamp | None,
        Field(description="Expires at for this context response."),
    ]
    archived_at: Annotated[
        AwareTimestamp | None,
        Field(description="Archived at for this context response."),
    ]
    access_count: Annotated[
        int, Field(description="Access count for this context response.")
    ]
    is_archived: Annotated[
        bool, Field(description="Is archived for this context response.")
    ]


class ContextListResponse(StrictSchemaModel):
    """Paginated context list response."""

    items: Annotated[
        list[ContextResponse],
        Field(description="Items for this context list response."),
    ]
    total: Annotated[int, Field(description="Total for this context list response.")]


class ContextSupersedeRequest(StrictSchemaModel):
    """Request to link one canonical Context to its replacement."""

    replacement_context_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(
            description="Replacement context identifier for this context supersede request."
        ),
    ]

    @field_validator("replacement_context_id")
    @classmethod
    def normalize_replacement_context_id(cls, value: str) -> str:
        """Normalize and reject a blank replacement identifier.

        Args:
            value: Raw replacement Context identifier.

        Returns:
            Trimmed replacement Context identifier.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("replacement_context_id must not be blank")
        return normalized


class ContextSupersedeResponse(StrictSchemaModel):
    """Bidirectional canonical Context supersede result."""

    superseded: Annotated[
        ContextResponse,
        Field(description="Superseded for this context supersede response."),
    ]
    replacement: Annotated[
        ContextResponse,
        Field(description="Replacement for this context supersede response."),
    ]


class ContextChunkResponse(StrictSchemaModel):
    """Stored context chunk response."""

    id: Annotated[
        str, Field(description="Stable identifier for this context chunk response.")
    ]
    context_id: Annotated[
        str, Field(description="Context identifier for this context chunk response.")
    ]
    chunk_index: Annotated[
        int, Field(description="Chunk index for this context chunk response.")
    ]
    heading: Annotated[
        str | None, Field(description="Heading for this context chunk response.")
    ]
    content: Annotated[
        str, Field(description="Content for this context chunk response.")
    ]
    token_count: Annotated[
        int, Field(description="Token count for this context chunk response.")
    ]
    content_hash: Annotated[
        str, Field(description="Content hash for this context chunk response.")
    ]
    metadata: Annotated[
        JSONObject, Field(description="Metadata for this context chunk response.")
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(description="Creation timestamp for this context chunk response."),
    ]


class ContextChunkResponseList(StrictRootSchemaModel[list[ContextChunkResponse]]):
    """Root response schema for context chunks."""


class ContextAccessEventRequest(StrictSchemaModel):
    """Payload for recording one Context Vault access event."""

    actor_name: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Actor name for this context access event request."),
    ] = "Alexandria UI"
    actor_type: Annotated[
        ContextAccessActorType,
        Field(description="Actor type for this context access event request."),
    ] = ContextAccessActorType.UI
    access_method: Annotated[
        ContextAccessMethod,
        Field(description="Access method for this context access event request."),
    ] = ContextAccessMethod.DETAIL_VIEW
    source_surface: Annotated[
        str | None,
        Field(description="Source surface for this context access event request."),
    ] = "context-detail"


class ContextAccessEventResponse(StrictSchemaModel):
    """Stored context access event response."""

    id: Annotated[
        str,
        Field(description="Stable identifier for this context access event response."),
    ]
    context_id: Annotated[
        str,
        Field(description="Context identifier for this context access event response."),
    ]
    accessed_at: Annotated[
        AwareTimestamp,
        Field(description="Accessed at for this context access event response."),
    ]
    actor_name: Annotated[
        str, Field(description="Actor name for this context access event response.")
    ]
    actor_type: Annotated[
        ContextAccessActorType,
        Field(description="Actor type for this context access event response."),
    ]
    access_method: Annotated[
        ContextAccessMethod,
        Field(description="Access method for this context access event response."),
    ]
    source_surface: Annotated[
        str | None,
        Field(description="Source surface for this context access event response."),
    ]


class ContextAccessEventResponseList(
    StrictRootSchemaModel[list[ContextAccessEventResponse]]
):
    """Root response schema for context access event arrays."""
