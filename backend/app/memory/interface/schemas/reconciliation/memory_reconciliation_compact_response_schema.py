"""Strict reconciliation-aware Memory Compact response schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactFact,
    MemoryCompactFactBuckets,
    MemoryCompactSafetyReview,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryCompactFactCategory,
    MemoryCompactSafetyIssue,
)
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp


class MemoryCompactFactResponse(StrictSchemaModel):
    """One temporally classified fact prepared for safe compaction."""

    context_id: Annotated[
        str,
        Field(description="Context identifier for this memory compact fact response."),
    ]
    title: Annotated[
        str, Field(description="Title for this memory compact fact response.")
    ]
    content: Annotated[
        str, Field(description="Content for this memory compact fact response.")
    ]
    category: Annotated[
        MemoryCompactFactCategory,
        Field(description="Category for this memory compact fact response."),
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        Field(description="Valid from for this memory compact fact response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        Field(description="Valid to for this memory compact fact response."),
    ]
    evidence_refs: Annotated[
        list[str],
        Field(description="Evidence refs for this memory compact fact response."),
    ]
    conflict_set_ids: Annotated[
        list[str],
        Field(
            description="Conflict set identifiers for this memory compact fact response."
        ),
    ]
    relation_summary: Annotated[
        list[str],
        Field(description="Relation summary for this memory compact fact response."),
    ]

    @classmethod
    def from_entity(cls, value: MemoryCompactFact) -> MemoryCompactFactResponse:
        """Convert one internal fact into a strict HTTP response.

        Args:
            value: Value.

        Returns:
            MemoryCompactFactResponse: Operation result.
        """
        return cls(
            context_id=value.context_id,
            title=value.title,
            content=value.content,
            category=value.category,
            valid_from=value.valid_from,
            valid_to=value.valid_to,
            evidence_refs=list(value.evidence_refs),
            conflict_set_ids=list(value.conflict_set_ids),
            relation_summary=list(value.relation_summary),
        )


class MemoryCompactFactBucketsResponse(StrictSchemaModel):
    """Fact sections that must remain separate during Memory Compact generation."""

    current_facts: Annotated[
        list[MemoryCompactFactResponse],
        Field(
            description="Current facts for this memory compact fact buckets response."
        ),
    ]
    historical_facts: Annotated[
        list[MemoryCompactFactResponse],
        Field(
            description="Historical facts for this memory compact fact buckets response."
        ),
    ]
    open_conflicts: Annotated[
        list[MemoryCompactFactResponse],
        Field(
            description="Open conflicts for this memory compact fact buckets response."
        ),
    ]
    uncertain_claims: Annotated[
        list[MemoryCompactFactResponse],
        Field(
            description="Uncertain claims for this memory compact fact buckets response."
        ),
    ]
    superseded_facts: Annotated[
        list[MemoryCompactFactResponse],
        Field(
            description="Superseded facts for this memory compact fact buckets response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryCompactFactBuckets,
    ) -> MemoryCompactFactBucketsResponse:
        """Convert all reconciliation-aware fact buckets into HTTP responses.

        Args:
            value: Value.

        Returns:
            MemoryCompactFactBucketsResponse: Operation result.
        """
        return cls(
            current_facts=[
                MemoryCompactFactResponse.from_entity(item)
                for item in value.current_facts
            ],
            historical_facts=[
                MemoryCompactFactResponse.from_entity(item)
                for item in value.historical_facts
            ],
            open_conflicts=[
                MemoryCompactFactResponse.from_entity(item)
                for item in value.open_conflicts
            ],
            uncertain_claims=[
                MemoryCompactFactResponse.from_entity(item)
                for item in value.uncertain_claims
            ],
            superseded_facts=[
                MemoryCompactFactResponse.from_entity(item)
                for item in value.superseded_facts
            ],
        )


class MemoryCompactSafetyReviewResponse(StrictSchemaModel):
    """Safe pre-publication review for reconciliation-aware Memory Compact input."""

    buckets: Annotated[
        MemoryCompactFactBucketsResponse,
        Field(description="Buckets for this memory compact safety review response."),
    ]
    issues: Annotated[
        list[MemoryCompactSafetyIssue],
        Field(description="Issues for this memory compact safety review response."),
    ]
    safe_to_publish: Annotated[
        bool,
        Field(
            description="Safe to publish for this memory compact safety review response."
        ),
    ]
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this memory compact safety review response."),
    ]
    rendered_markdown: Annotated[
        str,
        Field(
            description="Rendered markdown for this memory compact safety review response."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryCompactSafetyReview,
    ) -> MemoryCompactSafetyReviewResponse:
        """Convert one Compact safety review into a strict HTTP response.

        Args:
            value: Value.

        Returns:
            MemoryCompactSafetyReviewResponse: Operation result.
        """
        return cls(
            buckets=MemoryCompactFactBucketsResponse.from_entity(value.buckets),
            issues=list(value.issues),
            safe_to_publish=value.safe_to_publish,
            warnings=list(value.warnings),
            rendered_markdown=value.rendered_markdown,
        )
