"""Schemas for Memory Compact HTTP boundaries."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.memory.application.memory_compacts.lifecycle.memory_compact_signature import (
    body_hash,
    compact_state_hash,
)
from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
    MemoryStewardReadinessWarningCode,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MemoryCompactSourceRefRequest(StrictSchemaModel):
    """Request schema for a compact source reference."""

    source_type: Annotated[
        NonBlankString,
        Field(description="Source type for this memory compact source ref request."),
    ]
    source_id: Annotated[
        NonBlankString,
        Field(
            description="Source identifier for this memory compact source ref request."
        ),
    ]
    title: Annotated[
        NonBlankString,
        Field(description="Title for this memory compact source ref request."),
    ]
    detail_path: Annotated[
        NonBlankString,
        Field(description="Detail path for this memory compact source ref request."),
    ]
    source_hash: Annotated[
        str | None,
        Field(description="Source hash for this memory compact source ref request."),
    ] = None

    def to_create(self) -> MemoryCompactSourceRefCreate:
        """Convert request schema to service contract.

        Returns:
            Repository source-reference creation contract.
        """
        return MemoryCompactSourceRefCreate(
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            detail_path=self.detail_path,
            source_hash=self.source_hash,
        )


class MemoryCompactCreateRequest(StrictSchemaModel):
    """Request schema for creating a Memory Compact."""

    project: Annotated[
        str | None, Field(description="Project for this memory compact create request.")
    ] = None
    covered_from: Annotated[
        AwareTimestamp,
        Field(description="Covered from for this memory compact create request."),
    ]
    covered_to: Annotated[
        AwareTimestamp,
        Field(description="Covered to for this memory compact create request."),
    ]
    markdown_body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Markdown body for this memory compact create request."),
    ]
    status: Annotated[
        MemoryCompactStatus,
        Field(description="Status for this memory compact create request."),
    ] = MemoryCompactStatus.DRAFT
    source_refs: Annotated[
        list[MemoryCompactSourceRefRequest],
        Field(description="Source refs for this memory compact create request."),
    ] = schema_list_default()

    def to_create(self) -> MemoryCompactCreate:
        """Convert request schema to service contract.

        Returns:
            Repository creation contract.
        """
        return MemoryCompactCreate(
            project=self.project,
            covered_from=self.covered_from,
            covered_to=self.covered_to,
            markdown_body=self.markdown_body,
            status=MemoryCompactStatus(self.status),
            source_refs=tuple(
                source_ref.to_create() for source_ref in self.source_refs
            ),
        )


class MemoryCompactSourceRefResponse(StrictSchemaModel):
    """Response schema for compact source references."""

    id: Annotated[
        str,
        Field(
            description="Stable identifier for this memory compact source ref response."
        ),
    ]
    compact_id: Annotated[
        str,
        Field(
            description="Compact identifier for this memory compact source ref response."
        ),
    ]
    source_type: Annotated[
        str,
        Field(description="Source type for this memory compact source ref response."),
    ]
    source_id: Annotated[
        str,
        Field(
            description="Source identifier for this memory compact source ref response."
        ),
    ]
    title: Annotated[
        str, Field(description="Title for this memory compact source ref response.")
    ]
    detail_path: Annotated[
        str,
        Field(description="Detail path for this memory compact source ref response."),
    ]
    source_hash: Annotated[
        str | None,
        Field(description="Source hash for this memory compact source ref response."),
    ]

    @classmethod
    def from_entity(
        cls, source_ref: MemoryCompactSourceRef
    ) -> MemoryCompactSourceRefResponse:
        """Create response from domain entity.

        Args:
            source_ref: Domain source-reference entity.

        Returns:
            Public source-reference response schema.
        """
        return cls(
            id=source_ref.id,
            compact_id=source_ref.compact_id,
            source_type=source_ref.source_type,
            source_id=source_ref.source_id,
            title=source_ref.title,
            detail_path=source_ref.detail_path,
            source_hash=source_ref.source_hash,
        )


class MemoryCompactRagGateResponse(StrictSchemaModel):
    """RAG healthy-gate result attached to CURRENT create/promote responses."""

    gate_status: Annotated[
        str, Field(description="Gate status for this memory compact RAG gate response.")
    ]
    checked_at: Annotated[
        AwareTimestamp,
        Field(description="Checked at for this memory compact RAG gate response."),
    ]
    fingerprint: Annotated[
        JSONObject | None,
        Field(description="Fingerprint for this memory compact RAG gate response."),
    ]
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this memory compact RAG gate response."),
    ] = schema_list_default()


class MemoryCompactResponse(StrictSchemaModel):
    """Response schema for one Memory Compact."""

    draft_hash: Annotated[
        str | None,
        Field(description="Current snapshot fence for canonical DRAFT editing."),
    ] = None
    reviewed_body_hash: Annotated[
        str | None,
        Field(description="Body hash admitted by the last promotion review."),
    ] = None
    current_body_hash: Annotated[
        str | None, Field(description="Current canonical semantic body hash.")
    ] = None
    review_attestation_status: Annotated[
        str, Field(description="VERIFIED, STALE or MISSING body-review evidence.")
    ] = "MISSING"
    review_receipt_hash: Annotated[
        str | None, Field(description="Persisted source/body review receipt.")
    ] = None

    id: Annotated[
        str, Field(description="Stable identifier for this memory compact response.")
    ]
    project: Annotated[
        str | None, Field(description="Project for this memory compact response.")
    ]
    covered_from: Annotated[
        AwareTimestamp,
        Field(description="Covered from for this memory compact response."),
    ]
    covered_to: Annotated[
        AwareTimestamp,
        Field(description="Covered to for this memory compact response."),
    ]
    markdown_body: Annotated[
        str, Field(description="Markdown body for this memory compact response.")
    ]
    status: Annotated[
        MemoryCompactStatus,
        Field(description="Status for this memory compact response."),
    ]
    source_refs: Annotated[
        list[MemoryCompactSourceRefResponse],
        Field(description="Source refs for this memory compact response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(description="Creation timestamp for this memory compact response."),
    ]
    updated_at: Annotated[
        AwareTimestamp,
        Field(description="Last-update timestamp for this memory compact response."),
    ]
    archived_at: Annotated[
        AwareTimestamp | None,
        Field(description="Archived at for this memory compact response."),
    ]
    review_verdict: Annotated[
        MemoryCompactReviewVerdict | None,
        Field(description="Review verdict for this memory compact response."),
    ]
    review_score: Annotated[
        int | None, Field(description="Review score for this memory compact response.")
    ]
    review_max_score: Annotated[
        int | None,
        Field(description="Review max score for this memory compact response."),
    ]
    reviewed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Reviewed at for this memory compact response."),
    ]
    source_set_hash: Annotated[
        str | None,
        Field(description="Deterministic source-set hash for Compact 2.0 provenance."),
    ]
    compaction_policy_version: Annotated[
        str | None,
        Field(description="Compaction policy version that generated this artifact."),
    ]
    generation_revision: Annotated[
        int | None,
        Field(description="Generation revision for this compact artifact."),
    ]
    generated_at: Annotated[
        AwareTimestamp | None,
        Field(description="Generation timestamp for this compact artifact."),
    ]
    source_count: Annotated[
        int,
        Field(description="Source count derived from canonical source references."),
    ]
    expansion_refs: Annotated[
        list[str],
        Field(
            description="Stable source expansion paths derived from source references."
        ),
    ]
    provenance_complete: Annotated[
        bool,
        Field(description="Whether the Compact 2.0 provenance seal is complete."),
    ]
    warnings: Annotated[
        list[str], Field(description="Warnings for this memory compact response.")
    ] = schema_list_default()
    deduplicated: Annotated[
        bool, Field(description="Deduplicated for this memory compact response.")
    ] = False
    rag_gate: Annotated[
        MemoryCompactRagGateResponse | None,
        Field(description="RAG gate for this memory compact response."),
    ] = None

    @classmethod
    def from_entity(
        cls,
        compact: MemoryCompact,
        warnings: list[str] | None = None,
        rag_gate: MemoryCompactRagGateResponse | None = None,
    ) -> MemoryCompactResponse:
        """Create response from domain entity.

        Args:
            compact: Domain Memory Compact entity.
            warnings: Additional response-only warning codes.
            rag_gate: Optional RAG gate result for create/promote calls.

        Returns:
            Public Memory Compact response schema.
        """
        return cls(
            id=compact.id,
            project=compact.project,
            covered_from=compact.covered_from,
            covered_to=compact.covered_to,
            markdown_body=compact.markdown_body,
            status=compact.status,
            source_refs=[
                MemoryCompactSourceRefResponse.from_entity(source_ref)
                for source_ref in compact.source_refs
            ],
            created_at=compact.created_at,
            updated_at=compact.updated_at,
            archived_at=compact.archived_at,
            review_verdict=compact.review_verdict,
            review_score=compact.review_score,
            review_max_score=compact.review_max_score,
            reviewed_at=compact.reviewed_at,
            draft_hash=compact_state_hash(compact)
            if compact.status is MemoryCompactStatus.DRAFT
            else None,
            reviewed_body_hash=compact.reviewed_body_hash,
            current_body_hash=body_hash(compact.markdown_body),
            review_attestation_status="MISSING"
            if compact.reviewed_body_hash is None
            else "VERIFIED"
            if compact.reviewed_body_hash == body_hash(compact.markdown_body)
            and compact.review_score == compact.review_max_score == 20
            else "STALE",
            review_receipt_hash=compact.review_receipt_hash,
            source_set_hash=compact.source_set_hash,
            compaction_policy_version=compact.compaction_policy_version,
            generation_revision=compact.generation_revision,
            generated_at=compact.generated_at,
            source_count=compact.source_count,
            expansion_refs=list(compact.expansion_refs),
            provenance_complete=compact.provenance_complete,
            warnings=_response_warnings(
                [*compact.metadata_warnings, *(warnings or [])]
            ),
            deduplicated=compact.deduplicated,
            rag_gate=rag_gate,
        )


class MemoryCompactListResponse(StrictSchemaModel):
    """Paginated Memory Compact response."""

    items: Annotated[
        list[MemoryCompactResponse],
        Field(description="Items for this memory compact list response."),
    ]
    total: Annotated[
        int, Field(description="Total for this memory compact list response.")
    ]


def _response_warnings(warnings: list[str]) -> list[str]:
    """Deduplicate and normalize compact warning codes for HTTP responses.

    Args:
        warnings: Raw metadata and freshness warning codes.

    Returns:
        Deduplicated list of normalized current compact warning codes.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        value = _current_warning_code(warning)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _current_warning_code(warning: str) -> str:
    """Normalize legacy compact metadata warning codes to current compact codes.

    Args:
        warning: Raw warning code string.

    Returns:
        Canonical current compact warning code string.
    """
    if warning == MemoryStewardReadinessWarningCode.MEMORY_COMPACT_STALE.value:
        return MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_STALE.value
    if (
        warning
        == MemoryStewardReadinessWarningCode.MEMORY_COMPACT_TIMESTAMP_MISSING.value
    ):
        return MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_TIMESTAMP_MISSING.value
    return warning
