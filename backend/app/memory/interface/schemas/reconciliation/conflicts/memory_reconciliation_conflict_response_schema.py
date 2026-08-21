"""Strict conflict response schemas for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.memory_reconciliation import (
    MemoryConflictSet,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class MemoryConflictResponse(StrictSchemaModel):
    """First-class unresolved or resolved memory conflict."""

    conflict_set_id: Annotated[
        str,
        described_field("Conflict set identifier for this memory conflict response."),
    ]
    context_ids: Annotated[
        list[str],
        described_field("Context identifiers for this memory conflict response."),
    ]
    candidate_id: Annotated[
        str, described_field("Candidate identifier for this memory conflict response.")
    ]
    subject_key: Annotated[
        str, described_field("Subject key for this memory conflict response.")
    ]
    claim_key: Annotated[
        str, described_field("Claim key for this memory conflict response.")
    ]
    scope: Annotated[
        ContextScope, described_field("Scope for this memory conflict response.")
    ]
    validity_overlap: Annotated[
        bool, described_field("Validity overlap for this memory conflict response.")
    ]
    reason: Annotated[str, described_field("Reason for this memory conflict response.")]
    status: Annotated[
        MemoryConflictStatus,
        described_field("Status for this memory conflict response."),
    ]
    resolution: Annotated[
        str | None, described_field("Resolution for this memory conflict response.")
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this memory conflict response."),
    ]
    resolved_at: Annotated[
        AwareTimestamp | None,
        described_field("Resolved at for this memory conflict response."),
    ]

    @classmethod
    def from_entity(cls, value: MemoryConflictSet) -> MemoryConflictResponse:
        """Map one internal conflict set into a strict response.

        Args:
            value: Immutable internal memory conflict set.

        Returns:
            Explicitly mapped conflict response.
        """
        return cls(
            conflict_set_id=value.conflict_set_id,
            context_ids=list(value.context_ids),
            candidate_id=value.candidate_id,
            subject_key=value.subject_key,
            claim_key=value.claim_key,
            scope=value.scope,
            validity_overlap=value.validity_overlap,
            reason=value.reason,
            status=value.status,
            resolution=value.resolution,
            created_at=value.created_at,
            resolved_at=value.resolved_at,
        )


class MemoryConflictListResponse(StrictSchemaModel):
    """Paginated-style list of durable memory conflicts."""

    items: Annotated[
        list[MemoryConflictResponse],
        described_field("Items for this memory conflict list response."),
    ]
    total: Annotated[
        int, described_field("Total for this memory conflict list response.")
    ]
