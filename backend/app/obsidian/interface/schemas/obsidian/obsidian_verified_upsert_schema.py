"""Strict HTTP contracts for logical verified upsert and verification."""

from __future__ import annotations

from typing import Annotated, cast

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.memory.domain.types.context_payload_types import ContextProvenancePayload
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_boundary import (
    ContextProvenanceBoundary,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedDuplicateSafety,
    ObsidianVerifiedProjectionStatus,
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertResult,
    ObsidianVerifiedUpsertSelector,
    ObsidianVerifiedUpsertVerification,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.interface.schemas.obsidian.obsidian_logical_identity_schema import (
    ObsidianLogicalIdentitySchema,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONValue


class ObsidianVerifiedUpsertRequestSchema(StrictSchemaModel):
    """Agent-facing logical write request with no arbitrary metadata channel."""

    identity: Annotated[
        ObsidianLogicalIdentitySchema,
        described_field("Canonical logical identity for this verified upsert."),
    ]
    title: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Canonical note title for this verified upsert."),
    ]
    body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=4_000_000),
        described_field("Canonical Markdown body for this verified upsert."),
    ]
    alexandria_type: Annotated[
        AlexandriaNoteType,
        described_field("Managed Alexandria note type for this verified upsert."),
    ]
    idempotency_key: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Retry-stable key for this verified upsert."),
    ]
    expected_content_hash: Annotated[
        str | None,
        StringConstraints(
            strict=True,
            min_length=64,
            max_length=64,
            pattern="^[0-9a-fA-F]{64}$",
        ),
        described_field("Optional compare-and-swap hash for an existing note."),
    ] = None
    tags: Annotated[
        list[str],
        described_field("Typed tags for this verified upsert.", max_length=64),
    ] = schema_list_default()
    provenance: Annotated[
        ContextProvenanceBoundary,
        described_field("Typed provenance for this verified upsert."),
    ] = Field(default_factory=ContextProvenanceBoundary)
    source: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        described_field("Source actor label for this verified upsert."),
    ] = "agent"

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: JSONValue) -> list[str]:
        """Normalize tags once at the external boundary."""
        return normalize_string_collection(value)

    @field_validator("idempotency_key", "source", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject whitespace-only retry and source labels."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("verified upsert text must not be blank")
        return normalized

    def to_command(self) -> ObsidianVerifiedUpsertRequest:
        """Convert the validated boundary request to the internal command."""
        provenance = self.provenance
        return ObsidianVerifiedUpsertRequest(
            identity=self.identity.to_identity(),
            title=self.title,
            body=self.body,
            alexandria_type=AlexandriaNoteType(self.alexandria_type),
            idempotency_key=self.idempotency_key,
            expected_content_hash=(
                None
                if self.expected_content_hash is None
                else self.expected_content_hash.lower()
            ),
            tags=tuple(self.tags),
            provenance=cast(
                ContextProvenancePayload,
                {
                    "source_actor_id": provenance.source_actor_id,
                    "source_actor_type": provenance.source_actor_type,
                    "source_run_id": provenance.source_run_id,
                    "external_run_id": provenance.external_run_id,
                    "artifact_refs": list(provenance.artifact_refs),
                    "evidence_refs": list(provenance.evidence_refs),
                    "confidence": provenance.confidence,
                },
            ),
            source=self.source,
        )


class ObsidianVerifiedUpsertSelectorSchema(StrictSchemaModel):
    """Exact or logical selector for the high-level verify composite."""

    identity: Annotated[
        ObsidianLogicalIdentitySchema | None,
        described_field("Logical identity selector for verified note diagnostics."),
    ] = None
    note_id: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=256),
        described_field("Exact note identifier selector."),
    ] = None
    path: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=2048),
        described_field("Exact managed path selector."),
    ] = None

    @model_validator(mode="after")
    def require_selector(self) -> ObsidianVerifiedUpsertSelectorSchema:
        """Require exactly one concrete selector at the interface boundary."""
        selected = sum(
            (
                self.identity is not None,
                self.note_id is not None,
                self.path is not None,
            )
        )
        if selected != 1:
            raise ValueError(
                "verified selector requires exactly one of identity, note_id, or path"
            )
        return self

    def to_selector(self) -> ObsidianVerifiedUpsertSelector:
        """Convert the selector after enforcing exactly one selector shape."""
        identity = None if self.identity is None else self.identity.to_identity()
        return ObsidianVerifiedUpsertSelector(
            identity=identity,
            note_id=self.note_id,
            path=self.path,
        )


class ObsidianVerifiedUpsertResponse(StrictSchemaModel):
    """Truthful logical write and projection evidence."""

    operation: Annotated[
        ObsidianVerifiedUpsertOperation,
        described_field("Observed verified-upsert operation."),
    ]
    idempotency_key: Annotated[
        str, described_field("Retry key for the verified-upsert response.")
    ]
    logical_identity: Annotated[
        ObsidianLogicalIdentitySchema,
        described_field("Logical identity resolved by the verified upsert."),
    ]
    note_id: Annotated[str, described_field("Canonical note identifier.")]
    canonical_path: Annotated[str, described_field("Canonical managed note path.")]
    content_hash: Annotated[str, described_field("Read-back source content hash.")]
    version: Annotated[int | None, described_field("Canonical source version.")]
    storage_status: Annotated[
        ObsidianVerifiedProjectionStatus,
        described_field("Durable source storage evidence."),
    ]
    readback_verified: Annotated[
        bool, described_field("Whether canonical source readback matched the write.")
    ]
    metadata_status: Annotated[
        ObsidianVerifiedProjectionStatus,
        described_field("Metadata/index projection evidence."),
    ]
    fts_status: Annotated[
        ObsidianVerifiedProjectionStatus,
        described_field("FTS projection evidence."),
    ]
    vector_status: Annotated[
        ObsidianVerifiedProjectionStatus,
        described_field("Vector projection evidence."),
    ]
    graph_edge_index_status: Annotated[
        ObsidianVerifiedProjectionStatus,
        described_field("Indexed graph-edge evidence."),
    ]
    graph_projection_status: Annotated[
        ObsidianVerifiedProjectionStatus,
        described_field("Graph projection evidence."),
    ]
    duplicate_safety: Annotated[
        ObsidianVerifiedDuplicateSafety,
        described_field("Logical duplicate-safety evidence."),
    ]
    warnings: Annotated[
        list[str], described_field("Bounded warnings for this verified upsert.")
    ]
    error_code: Annotated[
        str | None, described_field("Stable error code when degraded evidence exists.")
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianVerifiedUpsertResult,
    ) -> ObsidianVerifiedUpsertResponse:
        """Map the internal result to the HTTP response contract."""
        return cls(
            operation=result.operation,
            idempotency_key=result.idempotency_key,
            logical_identity=ObsidianLogicalIdentitySchema.from_identity(
                result.logical_identity
            ),
            note_id=result.note_id,
            canonical_path=result.canonical_path,
            content_hash=result.content_hash,
            version=result.version,
            storage_status=result.storage_status,
            readback_verified=result.readback_verified,
            metadata_status=result.metadata_status,
            fts_status=result.fts_status,
            vector_status=result.vector_status,
            graph_edge_index_status=result.graph_edge_index_status,
            graph_projection_status=result.graph_projection_status,
            duplicate_safety=result.duplicate_safety,
            warnings=list(result.warnings),
            error_code=result.error_code,
        )


class ObsidianVerifiedUpsertVerificationResponse(StrictSchemaModel):
    """Source and projection diagnosis for one logical note selector."""

    source_readable: Annotated[bool, described_field("Source readability evidence.")]
    canonical_identity_resolved: Annotated[
        bool, described_field("Canonical identity resolution evidence.")
    ]
    indexed: Annotated[bool, described_field("Metadata index evidence.")]
    vector_current: Annotated[
        bool | None, described_field("Vector freshness evidence when available.")
    ]
    graph_current: Annotated[
        bool | None, described_field("Graph freshness evidence when available.")
    ]
    duplicate_safe: Annotated[
        bool | None, described_field("Duplicate safety evidence.")
    ]
    temporal_authority_consistent: Annotated[
        bool | None, described_field("Temporal/authority evidence when available.")
    ]
    note_id: Annotated[str | None, described_field("Resolved note identifier.")]
    canonical_path: Annotated[str | None, described_field("Resolved managed path.")]
    content_hash: Annotated[str | None, described_field("Observed source hash.")]
    version: Annotated[int | None, described_field("Observed source version.")]
    warnings: Annotated[list[str], described_field("Bounded verification warnings.")]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianVerifiedUpsertVerification,
    ) -> ObsidianVerifiedUpsertVerificationResponse:
        """Map verification evidence to the HTTP response contract."""
        return cls(
            source_readable=result.source_readable,
            canonical_identity_resolved=result.canonical_identity_resolved,
            indexed=result.indexed,
            vector_current=result.vector_current,
            graph_current=result.graph_current,
            duplicate_safe=result.duplicate_safe,
            temporal_authority_consistent=result.temporal_authority_consistent,
            note_id=result.note_id,
            canonical_path=result.canonical_path,
            content_hash=result.content_hash,
            version=result.version,
            warnings=list(result.warnings),
        )
