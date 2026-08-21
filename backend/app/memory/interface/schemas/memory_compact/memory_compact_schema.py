"""Schemas for Memory Compact HTTP boundaries."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.memory_compact import (
    MemoryCompact,
    MemoryCompactSourceRef,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONObject
from pydantic import StringConstraints

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MemoryCompactSourceRefRequest(StrictSchemaModel):
    """Request schema for a compact source reference."""

    source_type: Annotated[
        NonBlankString,
        described_field("Source type for this memory compact source ref request."),
    ]
    source_id: Annotated[
        NonBlankString,
        described_field(
            "Source identifier for this memory compact source ref request."
        ),
    ]
    title: Annotated[
        NonBlankString,
        described_field("Title for this memory compact source ref request."),
    ]
    detail_path: Annotated[
        NonBlankString,
        described_field("Detail path for this memory compact source ref request."),
    ]
    source_hash: Annotated[
        str | None,
        described_field("Source hash for this memory compact source ref request."),
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
        str | None, described_field("Project for this memory compact create request.")
    ] = None
    covered_from: Annotated[
        AwareTimestamp,
        described_field("Covered from for this memory compact create request."),
    ]
    covered_to: Annotated[
        AwareTimestamp,
        described_field("Covered to for this memory compact create request."),
    ]
    markdown_body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Markdown body for this memory compact create request."),
    ]
    status: Annotated[
        MemoryCompactStatus,
        described_field("Status for this memory compact create request."),
    ] = MemoryCompactStatus.DRAFT
    source_refs: Annotated[
        list[MemoryCompactSourceRefRequest],
        described_field("Source refs for this memory compact create request."),
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
        described_field(
            "Stable identifier for this memory compact source ref response."
        ),
    ]
    compact_id: Annotated[
        str,
        described_field(
            "Compact identifier for this memory compact source ref response."
        ),
    ]
    source_type: Annotated[
        str, described_field("Source type for this memory compact source ref response.")
    ]
    source_id: Annotated[
        str,
        described_field(
            "Source identifier for this memory compact source ref response."
        ),
    ]
    title: Annotated[
        str, described_field("Title for this memory compact source ref response.")
    ]
    detail_path: Annotated[
        str, described_field("Detail path for this memory compact source ref response.")
    ]
    source_hash: Annotated[
        str | None,
        described_field("Source hash for this memory compact source ref response."),
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
        str, described_field("Gate status for this memory compact RAG gate response.")
    ]
    checked_at: Annotated[
        AwareTimestamp,
        described_field("Checked at for this memory compact RAG gate response."),
    ]
    fingerprint: Annotated[
        JSONObject | None,
        described_field("Fingerprint for this memory compact RAG gate response."),
    ]
    warnings: Annotated[
        list[str],
        described_field("Warnings for this memory compact RAG gate response."),
    ] = schema_list_default()


class MemoryCompactResponse(StrictSchemaModel):
    """Response schema for one Memory Compact."""

    id: Annotated[
        str, described_field("Stable identifier for this memory compact response.")
    ]
    project: Annotated[
        str | None, described_field("Project for this memory compact response.")
    ]
    covered_from: Annotated[
        AwareTimestamp,
        described_field("Covered from for this memory compact response."),
    ]
    covered_to: Annotated[
        AwareTimestamp, described_field("Covered to for this memory compact response.")
    ]
    markdown_body: Annotated[
        str, described_field("Markdown body for this memory compact response.")
    ]
    status: Annotated[
        MemoryCompactStatus, described_field("Status for this memory compact response.")
    ]
    source_refs: Annotated[
        list[MemoryCompactSourceRefResponse],
        described_field("Source refs for this memory compact response."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        described_field("Creation timestamp for this memory compact response."),
    ]
    updated_at: Annotated[
        AwareTimestamp,
        described_field("Last-update timestamp for this memory compact response."),
    ]
    archived_at: Annotated[
        AwareTimestamp | None,
        described_field("Archived at for this memory compact response."),
    ]
    review_verdict: Annotated[
        MemoryCompactReviewVerdict | None,
        described_field("Review verdict for this memory compact response."),
    ]
    review_score: Annotated[
        int | None, described_field("Review score for this memory compact response.")
    ]
    review_max_score: Annotated[
        int | None,
        described_field("Review max score for this memory compact response."),
    ]
    reviewed_at: Annotated[
        AwareTimestamp | None,
        described_field("Reviewed at for this memory compact response."),
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this memory compact response.")
    ] = schema_list_default()
    deduplicated: Annotated[
        bool, described_field("Deduplicated for this memory compact response.")
    ] = False
    rag_gate: Annotated[
        MemoryCompactRagGateResponse | None,
        described_field("RAG gate for this memory compact response."),
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
        described_field("Items for this memory compact list response."),
    ]
    total: Annotated[
        int, described_field("Total for this memory compact list response.")
    ]


def _response_warnings(warnings: list[str]) -> list[str]:
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
    if warning == "memory_compact_stale":
        return "current_memory_compact_stale"
    if warning == "memory_compact_timestamp_missing":
        return "current_memory_compact_timestamp_missing"
    return warning
