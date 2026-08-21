"""Strict reconciliation-aware Memory Compact response schemas."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactFact,
    MemoryCompactFactBuckets,
    MemoryCompactSafetyReview,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryCompactFactCategory,
    MemoryCompactSafetyIssue,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp


class MemoryCompactFactResponse(StrictSchemaModel):
    """One temporally classified fact prepared for safe compaction."""

    context_id: Annotated[
        str,
        described_field("Context identifier for this memory compact fact response."),
    ]
    title: Annotated[
        str, described_field("Title for this memory compact fact response.")
    ]
    content: Annotated[
        str, described_field("Content for this memory compact fact response.")
    ]
    category: Annotated[
        MemoryCompactFactCategory,
        described_field("Category for this memory compact fact response."),
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this memory compact fact response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this memory compact fact response."),
    ]
    evidence_refs: Annotated[
        list[str],
        described_field("Evidence refs for this memory compact fact response."),
    ]
    conflict_set_ids: Annotated[
        list[str],
        described_field(
            "Conflict set identifiers for this memory compact fact response."
        ),
    ]
    relation_summary: Annotated[
        list[str],
        described_field("Relation summary for this memory compact fact response."),
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
        described_field("Current facts for this memory compact fact buckets response."),
    ]
    historical_facts: Annotated[
        list[MemoryCompactFactResponse],
        described_field(
            "Historical facts for this memory compact fact buckets response."
        ),
    ]
    open_conflicts: Annotated[
        list[MemoryCompactFactResponse],
        described_field(
            "Open conflicts for this memory compact fact buckets response."
        ),
    ]
    uncertain_claims: Annotated[
        list[MemoryCompactFactResponse],
        described_field(
            "Uncertain claims for this memory compact fact buckets response."
        ),
    ]
    superseded_facts: Annotated[
        list[MemoryCompactFactResponse],
        described_field(
            "Superseded facts for this memory compact fact buckets response."
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
        described_field("Buckets for this memory compact safety review response."),
    ]
    issues: Annotated[
        list[MemoryCompactSafetyIssue],
        described_field("Issues for this memory compact safety review response."),
    ]
    safe_to_publish: Annotated[
        bool,
        described_field(
            "Safe to publish for this memory compact safety review response."
        ),
    ]
    warnings: Annotated[
        list[str],
        described_field("Warnings for this memory compact safety review response."),
    ]
    rendered_markdown: Annotated[
        str,
        described_field(
            "Rendered markdown for this memory compact safety review response."
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
