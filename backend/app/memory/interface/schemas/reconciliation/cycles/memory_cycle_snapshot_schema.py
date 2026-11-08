"""Strict response schemas for memory-cycle source and Compact snapshots."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.domain.entities.memory_cycle import (
    MemoryCycleCandidate,
    MemoryCycleCompactChange,
    MemoryCycleCompactSnapshot,
    MemoryCycleSourceSnapshot,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType
from app.shared.schemas.common_schemas import StrictSchemaModel


class MemoryCycleSourceSnapshotResponse(StrictSchemaModel):
    """Stable source identity included in cycle plan provenance."""

    context_id: Annotated[str, Field(description="Canonical Context identity.")]
    canonical_path: Annotated[str, Field(description="Canonical source path.")]
    content_hash: Annotated[str, Field(description="Canonical source content hash.")]
    source_revision: Annotated[
        str,
        Field(description="Canonical source body and metadata revision."),
    ]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleSourceSnapshot
    ) -> MemoryCycleSourceSnapshotResponse:
        """Map one source snapshot entity."""
        return cls(
            context_id=value.context_id,
            canonical_path=value.canonical_path,
            content_hash=value.content_hash,
            source_revision=value.source_revision,
        )


class MemoryCycleCompactSnapshotResponse(StrictSchemaModel):
    """Current Compact identity and provenance at plan time."""

    compact_id: Annotated[str, Field(description="Current Compact identity.")]
    content_hash: Annotated[str, Field(description="Current Compact body hash.")]
    source_set_hash: Annotated[
        str | None,
        Field(description="Current Compact source-set hash."),
    ]
    status: Annotated[
        MemoryCompactStatus, Field(description="Compact lifecycle status.")
    ]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleCompactSnapshot
    ) -> MemoryCycleCompactSnapshotResponse:
        """Map one Compact snapshot entity."""
        return cls(
            compact_id=value.compact_id,
            content_hash=value.content_hash,
            source_set_hash=value.source_set_hash,
            status=value.status,
        )


class MemoryCycleCandidateResponse(StrictSchemaModel):
    """Typed candidate bucket item."""

    context_id: Annotated[str, Field(description="Candidate Context identity.")]
    title: Annotated[str, Field(description="Candidate title.")]
    canonical_path: Annotated[str, Field(description="Candidate source path.")]
    content_hash: Annotated[str, Field(description="Candidate source content hash.")]
    relation: Annotated[
        MemoryRelationType | None,
        Field(description="Selected existing reconciliation relation."),
    ]
    target_context_ids: Annotated[
        list[str],
        Field(description="Existing Context targets considered by the plan."),
    ]
    child_plan_key: Annotated[
        str | None,
        Field(description="Stable existing child-plan idempotency key."),
    ]
    reason: Annotated[str, Field(description="Bounded relation explanation.")]
    requires_review: Annotated[
        bool,
        Field(description="Whether explicit review is required before mutation."),
    ]

    @classmethod
    def from_entity(cls, value: MemoryCycleCandidate) -> MemoryCycleCandidateResponse:
        """Map one candidate entity."""
        return cls(
            context_id=value.context_id,
            title=value.title,
            canonical_path=value.canonical_path,
            content_hash=value.content_hash,
            relation=value.relation,
            target_context_ids=list(value.target_context_ids),
            child_plan_key=value.child_plan_key,
            reason=value.reason,
            requires_review=value.requires_review,
        )


class MemoryCycleCompactChangeResponse(StrictSchemaModel):
    """Compact publication candidate and verification state."""

    status: Annotated[
        MemoryCompactStatus | None,
        Field(description="Candidate or persisted Compact lifecycle status."),
    ]
    compact_id: Annotated[str | None, Field(description="Persisted Compact identity.")]
    content_hash: Annotated[str | None, Field(description="Compact body hash.")]
    source_set_hash: Annotated[
        str | None, Field(description="Compact source-set hash.")
    ]
    review_verdict: Annotated[
        MemoryCompactReviewVerdict | None,
        Field(description="Canonical Compact review verdict when available."),
    ]
    safe_to_publish: Annotated[
        bool,
        Field(description="Whether existing Compact safety policy permits promotion."),
    ]
    warnings: Annotated[list[str], Field(description="Compact safety warnings.")]

    @classmethod
    def from_entity(
        cls, value: MemoryCycleCompactChange
    ) -> MemoryCycleCompactChangeResponse:
        """Map one Compact change entity."""
        return cls(
            status=value.status,
            compact_id=value.compact_id,
            content_hash=value.content_hash,
            source_set_hash=value.source_set_hash,
            review_verdict=value.review_verdict,
            safe_to_publish=value.safe_to_publish,
            warnings=list(value.warnings),
        )
