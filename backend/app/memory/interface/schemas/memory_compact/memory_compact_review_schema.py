"""Memory compact review schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
    MemoryCompactRubricScore,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default


class MemoryCompactSourceObservationRequest(StrictSchemaModel):
    """Accepted compatibility input; authoritative observations are server-owned."""

    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(
            description="Source identifier for this memory compact source observation request."
        ),
    ]
    detail_path: Annotated[
        str | None,
        Field(
            description="Detail path for this memory compact source observation request."
        ),
    ] = None
    current_source_hash: Annotated[
        str | None,
        Field(
            description="Current source hash for this memory compact source observation request."
        ),
    ] = None


class MemoryCompactReviewRequest(StrictSchemaModel):
    """Request schema for quality review of a Memory Compact."""

    source_observations: Annotated[
        list[MemoryCompactSourceObservationRequest],
        Field(
            description="Source observations for this memory compact review request."
        ),
    ] = schema_list_default()


class MemoryCompactRubricScoreResponse(StrictSchemaModel):
    """Response schema for a single rubric score."""

    code: Annotated[
        str, Field(description="Code for this memory compact rubric score response.")
    ]
    label: Annotated[
        str, Field(description="Label for this memory compact rubric score response.")
    ]
    score: Annotated[
        int, Field(description="Score for this memory compact rubric score response.")
    ]
    required: Annotated[
        bool,
        Field(description="Required for this memory compact rubric score response."),
    ]
    reasons: Annotated[
        list[str],
        Field(description="Reasons for this memory compact rubric score response."),
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
    """Response schema for Memory Compact quality review."""

    compact_id: Annotated[
        str,
        Field(
            description="Compact identifier for this memory compact review response."
        ),
    ]
    verdict: Annotated[
        MemoryCompactReviewVerdict,
        Field(description="Verdict for this memory compact review response."),
    ]
    total_score: Annotated[
        int, Field(description="Total score for this memory compact review response.")
    ]
    max_score: Annotated[
        int, Field(description="Max score for this memory compact review response.")
    ]
    scores: Annotated[
        list[MemoryCompactRubricScoreResponse],
        Field(description="Scores for this memory compact review response."),
    ]
    missing_refs: Annotated[
        list[str],
        Field(description="Missing refs for this memory compact review response."),
    ]
    contradictions: Annotated[
        list[str],
        Field(description="Contradictions for this memory compact review response."),
    ]
    stale_reasons: Annotated[
        list[str],
        Field(description="Stale reasons for this memory compact review response."),
    ]
    recommended_actions: Annotated[
        list[str],
        Field(
            description="Recommended actions for this memory compact review response."
        ),
    ]
    review_hash: Annotated[
        str,
        Field(
            description="Deterministic receipt hash binding the reviewed body, source refs, "
            "coverage, project, and current source evidence."
        ),
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
            review_hash=result.review_hash,
        )


class MemoryCompactMarkCurrentRequest(StrictSchemaModel):
    """Optional review-receipt fence for CURRENT promotion."""

    expected_review_hash: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=64, max_length=64),
        Field(
            description="Reviewed-receipt hash admitted by a prior review; a mismatch "
            "rejects the promotion before any CURRENT supersession."
        ),
    ] = None


class MemoryCompactDraftEditRequest(StrictSchemaModel):
    """Final semantic draft replacement bound to the prior read snapshot."""

    markdown_body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Final body that must pass a new 20/20 review."),
    ]
    expected_draft_hash: Annotated[
        str,
        StringConstraints(
            strict=True, min_length=64, max_length=64, pattern="^[0-9a-f]{64}$"
        ),
        Field(description="Exact draft state hash from the prior read."),
    ]
