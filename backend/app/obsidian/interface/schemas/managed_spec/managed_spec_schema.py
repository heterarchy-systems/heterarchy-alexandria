"""Strict HTTP schemas for prepare/complete managed-spec execution."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecCompleteRequest,
    ManagedSpecCompleteResult,
    ManagedSpecEnvelope,
    ManagedSpecExecutionContext,
    ManagedSpecIdentity,
    ManagedSpecOutputWriteResult,
    ManagedSpecPrepareRequest,
    ManagedSpecPrepareResult,
)
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecCompletionStatus,
    ManagedSpecPrepareStatus,
)
from app.shared.schemas.common_schemas import StrictRootSchemaModel, StrictSchemaModel

_NoteId = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512),
]
_IdempotencyKey = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512),
]
_Sha256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-f]{64}$",
    ),
]


class ManagedSpecIdentityRequest(StrictSchemaModel):
    """Exact managed-spec selector request."""

    note_id: Annotated[
        _NoteId,
        Field(description="Exact canonical note identifier for the execution spec."),
    ]

    def to_command(self) -> ManagedSpecIdentity:
        """Convert the external selector to its domain contract."""
        return ManagedSpecIdentity(note_id=self.note_id)


class ManagedSpecExecutionContextRequest(StrictSchemaModel):
    """Typed scheduler context used to fence policy/spec authority."""

    project: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=256),
        Field(description="Project identity for the logical managed-spec output."),
    ]
    workflow: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=256),
        Field(description="Workflow/report identity declared by the scheduler."),
    ]
    entity: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=256),
        Field(description="Entity identity for the logical managed-spec output."),
    ]
    edition: Annotated[
        str | None,
        Field(description="Optional edition identity for the logical output."),
    ] = None
    expected_policy_note_id: Annotated[
        _NoteId,
        Field(description="Trusted exact runtime-policy note identifier."),
    ]

    def to_command(self) -> ManagedSpecExecutionContext:
        """Convert the external context to its domain contract."""
        return ManagedSpecExecutionContext(
            project=self.project,
            workflow=self.workflow,
            entity=self.entity,
            edition=self.edition,
            expected_policy_note_id=self.expected_policy_note_id,
        )


class ManagedSpecPrepareRequestSchema(StrictSchemaModel):
    """Discriminated prepare request for managed-spec execution."""

    operation: Literal["prepare"] = "prepare"
    spec_identity: Annotated[
        ManagedSpecIdentityRequest,
        Field(description="Exact execution specification identity."),
    ]
    logical_date: Annotated[
        str,
        StringConstraints(
            strict=True,
            min_length=10,
            max_length=10,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
        Field(description="ISO calendar date for the logical execution."),
    ]
    idempotency_key: Annotated[
        _IdempotencyKey,
        Field(description="Retry identity for the prepare envelope."),
    ]
    execution_context: Annotated[
        ManagedSpecExecutionContextRequest,
        Field(description="Trusted typed execution context."),
    ]

    def to_command(self) -> ManagedSpecPrepareRequest:
        """Convert the external prepare request to its domain contract."""
        return ManagedSpecPrepareRequest(
            spec_identity=self.spec_identity.to_command(),
            logical_date=self.logical_date,
            idempotency_key=self.idempotency_key,
            execution_context=self.execution_context.to_command(),
        )


class ManagedSpecCompleteRequestSchema(StrictSchemaModel):
    """Discriminated complete request for managed-spec execution."""

    operation: Literal["complete"] = "complete"
    idempotency_key: Annotated[
        _IdempotencyKey,
        Field(description="Prepare idempotency key whose envelope will be completed."),
    ]
    prepared_envelope_hash: Annotated[
        _Sha256,
        Field(description="Exact hash returned by the durable prepare operation."),
    ]
    output_title: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        Field(description="Title for the caller-produced durable output."),
    ]
    output_body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Body for the caller-produced durable output."),
    ]
    expected_output_content_hash: Annotated[
        _Sha256 | None,
        Field(description="Optional CAS hash for an existing logical output."),
    ] = None

    def to_command(self) -> ManagedSpecCompleteRequest:
        """Convert the external complete request to its domain contract."""
        return ManagedSpecCompleteRequest(
            idempotency_key=self.idempotency_key,
            prepared_envelope_hash=self.prepared_envelope_hash,
            output_title=self.output_title,
            output_body=self.output_body,
            expected_output_content_hash=self.expected_output_content_hash,
        )


ManagedSpecRequestSchema = Annotated[
    ManagedSpecPrepareRequestSchema | ManagedSpecCompleteRequestSchema,
    Field(discriminator="operation"),
]


class ManagedSpecRequestBody(StrictRootSchemaModel[ManagedSpecRequestSchema]):
    """Strict JSON-mode HTTP body wrapper for the discriminated request."""


class ObsidianLogicalIdentityResponse(StrictSchemaModel):
    """Logical output identity independent of physical note path/id."""

    project: Annotated[str, Field(description="Project identity for the output.")]
    report: Annotated[
        str, Field(description="Workflow/report identity for the output.")
    ]
    date: Annotated[str, Field(description="Logical date for the output.")]
    entity: Annotated[str, Field(description="Entity identity for the output.")]
    edition: Annotated[
        str | None,
        Field(description="Optional edition identity for the output."),
    ] = None

    @classmethod
    def from_entity(
        cls,
        identity: ObsidianLogicalIdentity,
    ) -> ObsidianLogicalIdentityResponse:
        """Build a response from the logical identity entity."""
        return cls(
            project=identity.project,
            report=identity.report,
            date=identity.date,
            entity=identity.entity,
            edition=identity.edition,
        )


class ManagedSpecEnvelopeResponse(StrictSchemaModel):
    """Inert pinned reference envelope returned from prepare."""

    idempotency_key: Annotated[
        str,
        Field(description="Prepare idempotency key pinned by the envelope."),
    ]
    spec_note_id: Annotated[
        str,
        Field(description="Exact execution specification note identifier."),
    ]
    logical_identity: Annotated[
        ObsidianLogicalIdentityResponse,
        Field(description="Stable logical output identity."),
    ]
    policy_note_id: Annotated[
        str,
        Field(description="Exact runtime-policy note identifier."),
    ]
    policy_version: Annotated[
        int,
        Field(description="Pinned runtime-policy version."),
    ]
    policy_content_hash: Annotated[
        str,
        Field(description="Pinned runtime-policy content hash."),
    ]
    policy_body: Annotated[
        str,
        Field(description="Bounded pinned runtime-policy body."),
    ]
    spec_version: Annotated[
        int,
        Field(description="Pinned execution specification version."),
    ]
    spec_content_hash: Annotated[
        str,
        Field(description="Pinned execution specification content hash."),
    ]
    spec_body: Annotated[
        str,
        Field(description="Bounded pinned execution specification body."),
    ]
    allowed_workflow: Annotated[
        str,
        Field(description="Workflow the inert envelope is allowed to describe."),
    ]
    reference_only: Annotated[
        bool,
        Field(description="Whether the envelope is reference-only data."),
    ]
    may_expand_permissions: Annotated[
        bool,
        Field(description="Whether the envelope may expand caller permissions."),
    ]
    may_start_unrelated_work: Annotated[
        bool,
        Field(description="Whether the envelope may start unrelated work."),
    ]

    @classmethod
    def from_entity(cls, envelope: ManagedSpecEnvelope) -> ManagedSpecEnvelopeResponse:
        """Build a response from the domain envelope."""
        return cls(
            idempotency_key=envelope.idempotency_key,
            spec_note_id=envelope.spec_identity.note_id,
            logical_identity=ObsidianLogicalIdentityResponse.from_entity(
                envelope.logical_identity
            ),
            policy_note_id=envelope.policy_note_id,
            policy_version=envelope.policy_version,
            policy_content_hash=envelope.policy_content_hash,
            policy_body=envelope.policy_body,
            spec_version=envelope.spec_version,
            spec_content_hash=envelope.spec_content_hash,
            spec_body=envelope.spec_body,
            allowed_workflow=envelope.allowed_workflow,
            reference_only=envelope.reference_only,
            may_expand_permissions=envelope.may_expand_permissions,
            may_start_unrelated_work=envelope.may_start_unrelated_work,
        )


class ManagedSpecPrepareResponse(StrictSchemaModel):
    """Prepare response with a durable envelope hash."""

    operation: Literal["prepare"] = "prepare"
    status: Annotated[
        ManagedSpecPrepareStatus,
        Field(description="Prepare lifecycle status."),
    ]
    envelope: Annotated[
        ManagedSpecEnvelopeResponse,
        Field(description="Inert pinned managed-spec envelope."),
    ]
    envelope_hash: Annotated[
        str,
        Field(description="Hash fencing the exact prepare envelope."),
    ]

    @classmethod
    def from_entity(
        cls, result: ManagedSpecPrepareResult
    ) -> ManagedSpecPrepareResponse:
        """Build a response from a prepare result."""
        return cls(
            status=result.status,
            envelope=ManagedSpecEnvelopeResponse.from_entity(result.envelope),
            envelope_hash=result.envelope_hash,
        )


class ManagedSpecOutputResponse(StrictSchemaModel):
    """Verified output evidence returned by complete."""

    operation: Annotated[str, Field(description="Canonical output write operation.")]
    note_id: Annotated[str, Field(description="Canonical output note identifier.")]
    canonical_path: Annotated[str, Field(description="Canonical output note path.")]
    logical_identity: Annotated[
        ObsidianLogicalIdentityResponse,
        Field(description="Logical identity used for duplicate safety."),
    ]
    content_hash: Annotated[str, Field(description="Read-back output content hash.")]
    storage_durable: Annotated[
        bool,
        Field(description="Whether canonical source storage is durable."),
    ]
    readback_verified: Annotated[
        bool,
        Field(description="Whether output source readback was verified."),
    ]
    metadata_status: Annotated[
        str,
        Field(description="Metadata index state after output persistence."),
    ]
    fts_status: Annotated[
        str,
        Field(description="FTS projection state after output persistence."),
    ]
    vector_status: Annotated[
        str,
        Field(description="Vector projection state after output persistence."),
    ]
    graph_edge_index_status: Annotated[
        str,
        Field(description="Graph edge index state after output persistence."),
    ]
    graph_projection_status: Annotated[
        str,
        Field(description="Graph projection state after output persistence."),
    ]
    duplicate_safe: Annotated[
        bool,
        Field(description="Whether logical duplicate safety was verified."),
    ]
    warnings: Annotated[
        list[str],
        Field(description="Projection or recovery warnings for the output."),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ManagedSpecOutputWriteResult,
    ) -> ManagedSpecOutputResponse:
        """Build a response from verified output evidence."""
        return cls(
            operation=result.operation,
            note_id=result.note_id,
            canonical_path=result.canonical_path,
            logical_identity=ObsidianLogicalIdentityResponse.from_entity(
                result.logical_identity
            ),
            content_hash=result.content_hash,
            storage_durable=result.storage_durable,
            readback_verified=result.readback_verified,
            metadata_status=result.metadata_status,
            fts_status=result.fts_status,
            vector_status=result.vector_status,
            graph_edge_index_status=result.graph_edge_index_status,
            graph_projection_status=result.graph_projection_status,
            duplicate_safe=result.duplicate_safe,
            warnings=list(result.warnings),
        )


class ManagedSpecCompleteResponse(StrictSchemaModel):
    """Complete response with durable output/projection evidence."""

    operation: Literal["complete"] = "complete"
    status: Annotated[
        ManagedSpecCompletionStatus,
        Field(description="Complete lifecycle status."),
    ]
    envelope: Annotated[
        ManagedSpecEnvelopeResponse,
        Field(description="Pinned envelope used for completion."),
    ]
    envelope_hash: Annotated[
        str,
        Field(description="Hash fencing the exact prepare envelope."),
    ]
    output: Annotated[
        ManagedSpecOutputResponse,
        Field(description="Verified canonical output evidence."),
    ]

    @classmethod
    def from_entity(
        cls, result: ManagedSpecCompleteResult
    ) -> ManagedSpecCompleteResponse:
        """Build a response from a complete result."""
        return cls(
            status=result.status,
            envelope=ManagedSpecEnvelopeResponse.from_entity(result.envelope),
            envelope_hash=result.envelope_hash,
            output=ManagedSpecOutputResponse.from_entity(result.output),
        )


ManagedSpecResponseSchema = Annotated[
    ManagedSpecPrepareResponse | ManagedSpecCompleteResponse,
    Field(discriminator="operation"),
]
