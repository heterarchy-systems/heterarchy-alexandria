"""Context Vault request and response schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator

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
from app.shared.schemas.common_schemas import (
    StrictRootSchemaModel,
    StrictSchemaModel,
    described_field,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject


class ContextProvenanceResponse(StrictSchemaModel):
    """Generalized Context origin and evidence references."""

    source_actor_id: Annotated[
        str | None,
        described_field(
            "Source actor identifier for this context provenance response."
        ),
    ]
    source_actor_type: Annotated[
        ContextSourceType | None,
        described_field("Source actor type for this context provenance response."),
    ]
    source_run_id: Annotated[
        str | None,
        described_field("Source run identifier for this context provenance response."),
    ]
    external_run_id: Annotated[
        str | None,
        described_field(
            "External run identifier for this context provenance response."
        ),
    ]
    artifact_refs: Annotated[
        list[str],
        described_field("Artifact refs for this context provenance response."),
    ]
    evidence_refs: Annotated[
        list[str],
        described_field("Evidence refs for this context provenance response."),
    ]
    confidence: Annotated[
        ContextImportance | None,
        described_field("Confidence for this context provenance response."),
    ]


class ContextLifecycleResponse(StrictSchemaModel):
    """Context lifecycle, integrity, and supersede metadata."""

    status: Annotated[
        ContextRecallLifecycleStatus,
        described_field("Status for this context lifecycle response."),
    ]
    content_hash: Annotated[
        str | None, described_field("Content hash for this context lifecycle response.")
    ]
    version: Annotated[
        int | None, described_field("Version for this context lifecycle response.")
    ]
    supersedes_context_id: Annotated[
        str | None,
        described_field(
            "Supersedes context identifier for this context lifecycle response."
        ),
    ]
    superseded_by_context_id: Annotated[
        str | None,
        described_field(
            "Superseded by context identifier for this context lifecycle response."
        ),
    ]


class ContextResponse(StrictSchemaModel):
    """Stored context response."""

    id: Annotated[str, described_field("Stable identifier for this context response.")]
    canonical_context_id: Annotated[
        str, described_field("Canonical context identifier for this context response.")
    ]
    kind: Annotated[ContextKind, described_field("Kind for this context response.")]
    memory_function: Annotated[
        MemoryFunction | None,
        described_field("Functional memory role for this context response."),
    ]
    title: Annotated[str, described_field("Title for this context response.")]
    summary: Annotated[str, described_field("Summary for this context response.")]
    content: Annotated[str, described_field("Content for this context response.")]
    content_format: Annotated[
        ContextContentFormat,
        described_field("Content format for this context response."),
    ]
    project: Annotated[
        str | None, described_field("Project for this context response.")
    ]
    scope: Annotated[ContextScope, described_field("Scope for this context response.")]
    workspace_id: Annotated[
        str | None, described_field("Workspace identifier for this context response.")
    ]
    agent_id: Annotated[
        str | None, described_field("Agent identifier for this context response.")
    ]
    user_id: Annotated[
        str | None, described_field("User identifier for this context response.")
    ]
    session_id: Annotated[
        str | None, described_field("Session identifier for this context response.")
    ]
    visibility: Annotated[
        ContextScope, described_field("Visibility for this context response.")
    ]
    source_agent: Annotated[
        str, described_field("Source agent for this context response.")
    ]
    source_type: Annotated[
        ContextSourceType, described_field("Source type for this context response.")
    ]
    importance: Annotated[
        ContextImportance, described_field("Importance for this context response.")
    ]
    tags: Annotated[list[str], described_field("Tags for this context response.")]
    status: Annotated[
        ContextStorageStatus, described_field("Status for this context response.")
    ]
    lifecycle_status: Annotated[
        ContextRecallLifecycleStatus,
        described_field("Lifecycle status for this context response."),
    ]
    provenance: Annotated[
        ContextProvenanceResponse,
        described_field("Provenance for this context response."),
    ]
    lifecycle: Annotated[
        ContextLifecycleResponse,
        described_field("Lifecycle for this context response."),
    ]
    quality_score: Annotated[
        int, described_field("Quality score for this context response.")
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this context response.")
    ]
    restore_prompt: Annotated[
        str | None, described_field("Restore prompt for this context response.")
    ]
    metadata: Annotated[
        JSONObject, described_field("Metadata for this context response.")
    ]
    created_at: Annotated[
        AwareTimestamp, described_field("Creation timestamp for this context response.")
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field("Last-update timestamp for this context response."),
    ]
    last_accessed_at: Annotated[
        AwareTimestamp | None,
        described_field("Last accessed at for this context response."),
    ]
    expires_at: Annotated[
        AwareTimestamp | None, described_field("Expires at for this context response.")
    ]
    archived_at: Annotated[
        AwareTimestamp | None, described_field("Archived at for this context response.")
    ]
    access_count: Annotated[
        int, described_field("Access count for this context response.")
    ]
    is_archived: Annotated[
        bool, described_field("Is archived for this context response.")
    ]


class ContextListResponse(StrictSchemaModel):
    """Paginated context list response."""

    items: Annotated[
        list[ContextResponse], described_field("Items for this context list response.")
    ]
    total: Annotated[int, described_field("Total for this context list response.")]


class ContextSupersedeRequest(StrictSchemaModel):
    """Request to link one canonical Context to its replacement."""

    replacement_context_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field(
            "Replacement context identifier for this context supersede request."
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
        described_field("Superseded for this context supersede response."),
    ]
    replacement: Annotated[
        ContextResponse,
        described_field("Replacement for this context supersede response."),
    ]


class ContextChunkResponse(StrictSchemaModel):
    """Stored context chunk response."""

    id: Annotated[
        str, described_field("Stable identifier for this context chunk response.")
    ]
    context_id: Annotated[
        str, described_field("Context identifier for this context chunk response.")
    ]
    chunk_index: Annotated[
        int, described_field("Chunk index for this context chunk response.")
    ]
    heading: Annotated[
        str | None, described_field("Heading for this context chunk response.")
    ]
    content: Annotated[str, described_field("Content for this context chunk response.")]
    token_count: Annotated[
        int, described_field("Token count for this context chunk response.")
    ]
    content_hash: Annotated[
        str, described_field("Content hash for this context chunk response.")
    ]
    metadata: Annotated[
        JSONObject, described_field("Metadata for this context chunk response.")
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this context chunk response."),
    ]


class ContextChunkResponseList(StrictRootSchemaModel[list[ContextChunkResponse]]):
    """Root response schema for context chunks."""


class ContextAccessEventRequest(StrictSchemaModel):
    """Payload for recording one Context Vault access event."""

    actor_name: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Actor name for this context access event request."),
    ] = "Alexandria UI"
    actor_type: Annotated[
        ContextAccessActorType,
        described_field("Actor type for this context access event request."),
    ] = ContextAccessActorType.UI
    access_method: Annotated[
        ContextAccessMethod,
        described_field("Access method for this context access event request."),
    ] = ContextAccessMethod.DETAIL_VIEW
    source_surface: Annotated[
        str | None,
        described_field("Source surface for this context access event request."),
    ] = "context-detail"


class ContextAccessEventResponse(StrictSchemaModel):
    """Stored context access event response."""

    id: Annotated[
        str,
        described_field("Stable identifier for this context access event response."),
    ]
    context_id: Annotated[
        str,
        described_field("Context identifier for this context access event response."),
    ]
    accessed_at: Annotated[
        AwareTimestamp,
        described_field("Accessed at for this context access event response."),
    ]
    actor_name: Annotated[
        str, described_field("Actor name for this context access event response.")
    ]
    actor_type: Annotated[
        ContextAccessActorType,
        described_field("Actor type for this context access event response."),
    ]
    access_method: Annotated[
        ContextAccessMethod,
        described_field("Access method for this context access event response."),
    ]
    source_surface: Annotated[
        str | None,
        described_field("Source surface for this context access event response."),
    ]


class ContextAccessEventResponseList(
    StrictRootSchemaModel[list[ContextAccessEventResponse]]
):
    """Root response schema for context access event arrays."""
