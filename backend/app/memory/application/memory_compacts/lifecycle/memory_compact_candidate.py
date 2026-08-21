"""Memory Compact candidate normalization and review mapping."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.memory_compacts.lifecycle.memory_compact_policy import (
    ensure_review_passes,
    missing_current_sections,
)
from app.memory.application.memory_compacts.review.memory_compact_review import (
    review_memory_compact,
)
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactValidationError
from app.shared.types.types_convert_utils import aware_utc_datetime, enum_value


def normalized_create(payload: MemoryCompactCreate) -> MemoryCompactCreate:
    """Normalize and validate one creation payload.

    Args:
        payload: Memory Compact creation contract.

    Returns:
        Normalized and reviewed creation payload.
    """
    normalized = MemoryCompactCreate(
        project=payload.project,
        covered_from=payload.covered_from,
        covered_to=payload.covered_to,
        markdown_body=payload.markdown_body,
        status=enum_value(payload.status, MemoryCompactStatus, "status"),
        source_refs=_deduplicate_source_refs(payload.source_refs),
        review_verdict=payload.review_verdict,
        review_score=payload.review_score,
        review_max_score=payload.review_max_score,
        reviewed_at=payload.reviewed_at,
    )
    _validate_create(normalized)
    if normalized.status is not MemoryCompactStatus.CURRENT:
        return normalized
    review = review_memory_compact(candidate_compact(normalized))
    ensure_review_passes(review)
    return with_review_metadata(normalized, review)


def candidate_compact(payload: MemoryCompactCreate) -> MemoryCompact:
    """Build a non-persisted entity for rubric review.

    Args:
        payload: Normalized creation payload.

    Returns:
        Candidate Memory Compact entity.
    """
    covered_from = aware_utc_datetime(payload.covered_from)
    covered_to = aware_utc_datetime(payload.covered_to)
    return MemoryCompact(
        id="__candidate__",
        project=payload.project,
        covered_from=covered_from,
        covered_to=covered_to,
        markdown_body=payload.markdown_body,
        status=payload.status,
        source_refs=tuple(
            MemoryCompactSourceRef(
                id=f"__candidate_source_{index}__",
                compact_id="__candidate__",
                source_type=source_ref.source_type,
                source_id=source_ref.source_id,
                title=source_ref.title,
                detail_path=source_ref.detail_path,
                source_hash=source_ref.source_hash,
            )
            for index, source_ref in enumerate(payload.source_refs)
        ),
        created_at=covered_to,
        updated_at=covered_to,
        archived_at=None,
        review_verdict=payload.review_verdict,
        review_score=payload.review_score,
        review_max_score=payload.review_max_score,
        reviewed_at=payload.reviewed_at,
    )


def with_review_metadata(
    payload: MemoryCompactCreate,
    review: MemoryCompactReviewResult,
) -> MemoryCompactCreate:
    """Return a creation payload enriched with rubric review metadata.

    Args:
        payload: Normalized creation payload.
        review: Passing review result.

    Returns:
        Creation payload with review metadata.
    """
    return MemoryCompactCreate(
        project=payload.project,
        covered_from=payload.covered_from,
        covered_to=payload.covered_to,
        markdown_body=payload.markdown_body,
        status=payload.status,
        source_refs=payload.source_refs,
        review_verdict=review.verdict,
        review_score=review.total_score,
        review_max_score=review.max_score,
        reviewed_at=datetime.now(UTC),
    )


def _validate_create(payload: MemoryCompactCreate) -> None:
    if payload.covered_to < payload.covered_from:
        raise MemoryCompactValidationError("covered_to must be after covered_from")
    if not payload.markdown_body.strip():
        raise MemoryCompactValidationError("markdown_body is required")
    if payload.status is MemoryCompactStatus.CURRENT and not payload.source_refs:
        raise MemoryCompactValidationError(
            "Current memory compact requires source refs"
        )
    if payload.status is MemoryCompactStatus.CURRENT:
        missing_sections = missing_current_sections(payload.markdown_body)
        if missing_sections:
            raise MemoryCompactValidationError(
                "Current memory compact missing required sections: "
                + ", ".join(missing_sections)
            )
    for source_ref in payload.source_refs:
        if (
            not source_ref.source_type.strip()
            or not source_ref.source_id.strip()
            or not source_ref.title.strip()
            or not source_ref.detail_path.strip()
        ):
            raise MemoryCompactValidationError(
                "Memory compact source ref fields are required"
            )


def _deduplicate_source_refs(
    source_refs: tuple[MemoryCompactSourceRefCreate, ...],
) -> tuple[MemoryCompactSourceRefCreate, ...]:
    deduplicated: list[MemoryCompactSourceRefCreate] = []
    seen: set[tuple[str, str, str]] = set()
    for source_ref in source_refs:
        key = (source_ref.source_type, source_ref.source_id, source_ref.detail_path)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(source_ref)
    return tuple(deduplicated)
