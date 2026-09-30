"""HTTP/MCP contracts for the durable mutation outcome query."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import StringConstraints, field_validator, model_validator

from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    MutationOperationKind,
    ObsidianMutationOutcome,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    exclude_none_field,
)


class ObsidianMutationOutcomeRequestSchema(StrictSchemaModel):
    """Selector for one previously attempted fenced logical mutation."""

    operation: Annotated[
        Literal["verified_upsert", "relate", "note_write"],
        described_field("Fenced mutation kind that recorded the durable receipt."),
    ] = "note_write"
    idempotency_key: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Idempotency key the original mutation was sent with."),
    ] = None
    mutation_id: Annotated[
        str | None,
        StringConstraints(
            strict=True,
            min_length=75,
            max_length=75,
            pattern="^note-write:[0-9a-f]{64}$",
        ),
        described_field("Direct note-write receipt selector."),
    ] = None

    @model_validator(mode="after")
    def require_one_selector(self) -> ObsidianMutationOutcomeRequestSchema:
        """Require exactly one selector and keep direct IDs note-write scoped."""
        selected = sum((self.idempotency_key is not None, self.mutation_id is not None))
        if selected != 1:
            raise ValueError(
                "mutation outcome requires exactly one of idempotency_key or mutation_id"
            )
        if self.mutation_id is not None and self.operation != "note_write":
            raise ValueError("mutation_id lookup only supports note_write")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        return self


class ObsidianMutationOutcomeResponseSchema(StrictSchemaModel):
    """Truthful retry-safety verdict for one previously attempted mutation."""

    operation: Annotated[
        MutationOperationKind,
        described_field("Fenced mutation kind that was queried."),
    ]
    idempotency_key: Annotated[
        str | None, described_field("Idempotency key that was queried.")
    ]
    status: Annotated[
        ObsidianMutationOutcomeStatus,
        described_field("Retry-safety verdict assembled from durable fence evidence."),
    ]
    checkpoint_state: Annotated[
        str | None,
        described_field("Recorded fence state when a checkpoint exists."),
        exclude_none_field(),
    ] = None
    canonical_path: Annotated[
        str | None,
        described_field("Canonical source path the mutation targeted."),
        exclude_none_field(),
    ] = None
    note_id: Annotated[
        str | None,
        described_field("Canonical note identifier from fence or readback."),
        exclude_none_field(),
    ] = None
    content_hash: Annotated[
        str | None,
        described_field("Canonical source content hash evidence."),
        exclude_none_field(),
    ] = None
    version: Annotated[
        int | None,
        described_field("Canonical source version when available."),
        exclude_none_field(),
    ] = None
    evidence: Annotated[
        list[str],
        described_field("Bounded evidence codes supporting this verdict."),
    ]
    mutation_id: Annotated[
        str | None, described_field("Stable opaque mutation receipt identifier.")
    ] = None
    operation_identity: Annotated[
        str | None, described_field("Fingerprint of the admitted logical request.")
    ] = None
    committed_at: Annotated[
        datetime | None, described_field("Observed primary source commit timestamp.")
    ] = None
    error_summary: Annotated[
        str | None, described_field("Bounded failure category, excluding payloads.")
    ] = None
    replayed: Annotated[
        bool, described_field("Whether an exact readback replaced a new write.")
    ] = False

    @field_validator("committed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        """Reject a committed timestamp that cannot be placed on a timeline."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("committed_at must include an explicit timezone")
        return value

    @classmethod
    def from_entity(
        cls,
        outcome: ObsidianMutationOutcome,
    ) -> ObsidianMutationOutcomeResponseSchema:
        """Map one domain outcome into the public contract."""
        return cls(
            operation=outcome.operation,
            idempotency_key=outcome.idempotency_key,
            status=outcome.status,
            checkpoint_state=outcome.checkpoint_state,
            canonical_path=outcome.canonical_path,
            note_id=outcome.note_id,
            content_hash=outcome.content_hash,
            version=outcome.version,
            evidence=list(outcome.evidence),
            mutation_id=outcome.mutation_id,
            operation_identity=outcome.operation_identity,
            committed_at=outcome.committed_at,
            error_summary=outcome.error_summary,
            replayed=outcome.replayed,
        )
