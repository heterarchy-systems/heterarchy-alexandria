"""Memory compact review schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
    MemoryCompactRubricScore,
    MemoryCompactSourceObservation,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)


class MemoryCompactSourceObservationRequest(StrictSchemaModel):
    """Observed current source state for review-time freshness checks."""

    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field(
            "Source identifier for this memory compact source observation request."
        ),
    ]
    detail_path: Annotated[
        str | None,
        described_field(
            "Detail path for this memory compact source observation request."
        ),
    ] = None
    current_source_hash: Annotated[
        str | None,
        described_field(
            "Current source hash for this memory compact source observation request."
        ),
    ] = None

    def to_observation(self) -> MemoryCompactSourceObservation:
        """Convert request schema to application review input.

        Returns:
            Source observation dataclass.
        """
        return MemoryCompactSourceObservation(
            source_id=self.source_id,
            detail_path=self.detail_path,
            current_source_hash=self.current_source_hash,
        )


class MemoryCompactReviewRequest(StrictSchemaModel):
    """Request schema for librarian review of a Memory Compact."""

    source_observations: Annotated[
        list[MemoryCompactSourceObservationRequest],
        described_field("Source observations for this memory compact review request."),
    ] = schema_list_default()

    def to_observations(self) -> tuple[MemoryCompactSourceObservation, ...]:
        """Convert request schema to application review observations.

        Returns:
            Source observations tuple.
        """
        return tuple(
            observation.to_observation() for observation in self.source_observations
        )


class MemoryCompactRubricScoreResponse(StrictSchemaModel):
    """Response schema for a single rubric score."""

    code: Annotated[
        str, described_field("Code for this memory compact rubric score response.")
    ]
    label: Annotated[
        str, described_field("Label for this memory compact rubric score response.")
    ]
    score: Annotated[
        int, described_field("Score for this memory compact rubric score response.")
    ]
    required: Annotated[
        bool, described_field("Required for this memory compact rubric score response.")
    ]
    reasons: Annotated[
        list[str],
        described_field("Reasons for this memory compact rubric score response."),
    ]

    @classmethod
    def from_result(
        cls, score: MemoryCompactRubricScore
    ) -> MemoryCompactRubricScoreResponse:
        """Create response schema from rubric score.

        Args:
            score: Internal rubric score dataclass.

        Returns:
            Public rubric score response.
        """
        return cls(
            code=score.code,
            label=score.label,
            score=score.score,
            required=score.required,
            reasons=list(score.reasons),
        )


class MemoryCompactReviewResponse(StrictSchemaModel):
    """Response schema for librarian Memory Compact review."""

    compact_id: Annotated[
        str,
        described_field("Compact identifier for this memory compact review response."),
    ]
    verdict: Annotated[
        MemoryCompactReviewVerdict,
        described_field("Verdict for this memory compact review response."),
    ]
    total_score: Annotated[
        int, described_field("Total score for this memory compact review response.")
    ]
    max_score: Annotated[
        int, described_field("Max score for this memory compact review response.")
    ]
    scores: Annotated[
        list[MemoryCompactRubricScoreResponse],
        described_field("Scores for this memory compact review response."),
    ]
    missing_refs: Annotated[
        list[str],
        described_field("Missing refs for this memory compact review response."),
    ]
    contradictions: Annotated[
        list[str],
        described_field("Contradictions for this memory compact review response."),
    ]
    stale_reasons: Annotated[
        list[str],
        described_field("Stale reasons for this memory compact review response."),
    ]
    recommended_actions: Annotated[
        list[str],
        described_field("Recommended actions for this memory compact review response."),
    ]

    @classmethod
    def from_result(
        cls, result: MemoryCompactReviewResult
    ) -> MemoryCompactReviewResponse:
        """Create response schema from review result.

        Args:
            result: Application review result.

        Returns:
            Public review response.
        """
        return cls(
            compact_id=result.compact_id,
            verdict=result.verdict,
            total_score=result.total_score,
            max_score=result.max_score,
            scores=[
                MemoryCompactRubricScoreResponse.from_result(score)
                for score in result.scores
            ],
            missing_refs=list(result.missing_refs),
            contradictions=list(result.contradictions),
            stale_reasons=list(result.stale_reasons),
            recommended_actions=list(result.recommended_actions),
        )
