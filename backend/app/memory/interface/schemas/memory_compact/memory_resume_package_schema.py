"""Schemas for the resume context package HTTP boundary."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageAttributedItem,
    ResumePackageDraft,
    ResumePackageEvidenceRef,
    ResumePackageLineage,
    ResumePackageView,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.schemas.datetime_schemas import AwareTimestamp

NonBlankSingleLineString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"\A[^\n\r]+\z",
    ),
]


class MemoryResumePackageAttributionRequest(StrictSchemaModel):
    """Request schema for one attributed change or constraint."""

    text: Annotated[
        NonBlankSingleLineString,
        Field(description="Text of this accepted change or constraint."),
    ]
    source_context_id: Annotated[
        NonBlankSingleLineString,
        Field(description="Stored Context identifier attributing this item."),
    ]

    def to_item(self) -> ResumePackageAttributedItem:
        """Convert request schema to the attributed-item contract.

        Returns:
            Typed attributed item.
        """
        return ResumePackageAttributedItem(
            text=self.text,
            source_context_id=self.source_context_id,
        )


class MemoryResumePackageLineageRequest(StrictSchemaModel):
    """Request schema for resume package lineage identity.

    Seal fields (``previous_package_id`` / ``package_revision``) are assigned
    by the assembly service and are never accepted from callers.
    """

    lineage_id: Annotated[
        NonBlankSingleLineString,
        Field(description="Stable lineage identity for the handoff chain."),
    ]
    worker_id: Annotated[
        NonBlankSingleLineString | None,
        Field(description="Optional originating worker identity."),
    ] = None
    run_id: Annotated[
        NonBlankSingleLineString | None,
        Field(description="Optional originating run identity."),
    ] = None
    workspace_id: Annotated[
        NonBlankSingleLineString | None,
        Field(description="Optional workspace reference."),
    ] = None
    session_id: Annotated[
        NonBlankSingleLineString | None,
        Field(description="Optional session reference."),
    ] = None

    def to_lineage(self) -> ResumePackageLineage:
        """Convert request schema to the lineage contract.

        Returns:
            Typed draft lineage without sealed fields.
        """
        return ResumePackageLineage(
            lineage_id=self.lineage_id,
            worker_id=self.worker_id,
            run_id=self.run_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
        )


class MemoryResumePackageCreateRequest(StrictSchemaModel):
    """Request schema for sealing one versioned resume package."""

    project: Annotated[
        str | None,
        Field(description="Project scope recorded under Coverage."),
    ] = None
    goal: Annotated[
        NonBlankSingleLineString,
        Field(description="Original objective sourced from the caller."),
    ]
    summary: Annotated[
        NonBlankSingleLineString,
        Field(description="Single-line package summary."),
    ]
    current_state: Annotated[
        NonBlankSingleLineString,
        Field(description="Single-line current-state statement."),
    ]
    next_single_action: Annotated[
        NonBlankSingleLineString,
        Field(description="Single next action for the resuming worker."),
    ]
    covered_from: Annotated[
        AwareTimestamp,
        Field(description="Inclusive coverage start timestamp."),
    ]
    covered_to: Annotated[
        AwareTimestamp,
        Field(description="Coverage end timestamp."),
    ]
    lineage: Annotated[
        MemoryResumePackageLineageRequest,
        Field(description="Worker-handoff lineage identity."),
    ]
    evidence_context_ids: Annotated[
        list[NonBlankSingleLineString],
        Field(
            description="Stored Context identifiers observed as evidence; content hashes "
            "are computed server-side from stored content.",
            min_length=1,
        ),
    ]
    accepted_changes: Annotated[
        list[MemoryResumePackageAttributionRequest],
        Field(description="Accepted changes with source attribution."),
    ] = schema_list_default()
    constraints: Annotated[
        list[MemoryResumePackageAttributionRequest],
        Field(description="Constraints with source attribution."),
    ] = schema_list_default()
    verified_complete: Annotated[
        list[NonBlankSingleLineString],
        Field(description="Tasks verified complete by observed evidence."),
    ] = schema_list_default()
    implemented_unverified: Annotated[
        list[NonBlankSingleLineString],
        Field(description="Tasks implemented but not verified."),
    ] = schema_list_default()
    unfinished_tasks: Annotated[
        list[NonBlankSingleLineString],
        Field(description="Tasks intentionally left unfinished."),
    ] = schema_list_default()
    uncertain_results: Annotated[
        list[NonBlankSingleLineString],
        Field(description="Results whose confidence is uncertain."),
    ] = schema_list_default()
    blockers: Annotated[
        list[NonBlankSingleLineString],
        Field(description="Active blockers."),
    ] = schema_list_default()
    request_id: Annotated[
        NonBlankSingleLineString | None,
        Field(
            description="Optional caller retry-fencing identity. Retrying the same "
            "request id with different content is rejected with a typed "
            "conflict instead of sealing a new revision."
        ),
    ] = None

    def to_draft(self) -> ResumePackageDraft:
        """Convert request schema to the service draft contract.

        Returns:
            Typed resume package draft.
        """
        return ResumePackageDraft(
            project=self.project,
            goal=self.goal,
            summary=self.summary,
            current_state=self.current_state,
            next_single_action=self.next_single_action,
            covered_from=self.covered_from,
            covered_to=self.covered_to,
            lineage=self.lineage.to_lineage(),
            evidence_context_ids=tuple(self.evidence_context_ids),
            accepted_changes=tuple(item.to_item() for item in self.accepted_changes),
            constraints=tuple(item.to_item() for item in self.constraints),
            verified_complete=tuple(self.verified_complete),
            implemented_unverified=tuple(self.implemented_unverified),
            unfinished_tasks=tuple(self.unfinished_tasks),
            uncertain_results=tuple(self.uncertain_results),
            blockers=tuple(self.blockers),
            request_id=self.request_id,
        )


class MemoryResumePackageEvidenceRefResponse(StrictSchemaModel):
    """Response schema for one sealed evidence reference."""

    context_id: Annotated[
        str,
        Field(description="Stored Context identifier backing this evidence ref."),
    ]
    content_hash: Annotated[
        str,
        Field(description="Server-observed content hash at seal time."),
    ]
    source: Annotated[
        str,
        Field(description="Observed source identity of the Context record."),
    ]
    created_at: Annotated[
        AwareTimestamp,
        Field(description="Creation timestamp of the observed Context record."),
    ]
    observed_updated_at: Annotated[
        AwareTimestamp,
        Field(description="Last-update timestamp observed at seal time."),
    ]

    @classmethod
    def from_view(
        cls,
        evidence_ref: ResumePackageEvidenceRef,
    ) -> MemoryResumePackageEvidenceRefResponse:
        """Create response from the structured evidence reference.

        Args:
            evidence_ref: Observed evidence reference.

        Returns:
            Public evidence-reference response schema.
        """
        return cls(
            context_id=evidence_ref.context_id,
            content_hash=evidence_ref.content_hash,
            source=evidence_ref.source,
            created_at=evidence_ref.created_at,
            observed_updated_at=evidence_ref.observed_updated_at,
        )


class MemoryResumePackageResponse(StrictSchemaModel):
    """Response schema for one versioned resume package."""

    package_id: Annotated[
        str,
        Field(description="Memory Compact identifier of this resume package."),
    ]
    project: Annotated[
        str | None,
        Field(description="Project scope recorded under Coverage."),
    ]
    status: Annotated[
        MemoryCompactStatus,
        Field(description="Compact lifecycle status of this package artifact."),
    ]
    covered_from: Annotated[
        AwareTimestamp,
        Field(description="Inclusive coverage start timestamp."),
    ]
    covered_to: Annotated[
        AwareTimestamp,
        Field(description="Coverage end timestamp."),
    ]
    goal: Annotated[
        str,
        Field(description="Original objective sourced from the caller."),
    ]
    summary: Annotated[
        str,
        Field(description="Single-line package summary."),
    ]
    current_state: Annotated[
        str,
        Field(description="Single-line current-state statement."),
    ]
    next_single_action: Annotated[
        str,
        Field(description="Single next action for the resuming worker."),
    ]
    accepted_changes: Annotated[
        list[MemoryResumePackageAttributionRequest],
        Field(description="Accepted changes with source attribution."),
    ]
    constraints: Annotated[
        list[MemoryResumePackageAttributionRequest],
        Field(description="Constraints with source attribution."),
    ]
    verified_complete: Annotated[
        list[str],
        Field(description="Tasks verified complete by observed evidence."),
    ]
    implemented_unverified: Annotated[
        list[str],
        Field(description="Tasks implemented but not verified."),
    ]
    unfinished_tasks: Annotated[
        list[str],
        Field(description="Tasks intentionally left unfinished."),
    ]
    uncertain_results: Annotated[
        list[str],
        Field(description="Results whose confidence is uncertain."),
    ]
    blockers: Annotated[
        list[str],
        Field(description="Active blockers."),
    ]
    evidence_refs: Annotated[
        list[MemoryResumePackageEvidenceRefResponse],
        Field(description="Server-observed evidence references."),
    ]
    lineage_id: Annotated[
        str,
        Field(description="Stable lineage identity for the handoff chain."),
    ]
    worker_id: Annotated[
        str | None,
        Field(description="Optional originating worker identity."),
    ]
    run_id: Annotated[
        str | None,
        Field(description="Optional originating run identity."),
    ]
    workspace_id: Annotated[
        str | None,
        Field(description="Optional workspace reference."),
    ]
    session_id: Annotated[
        str | None,
        Field(description="Optional session reference."),
    ]
    previous_package_id: Annotated[
        str | None,
        Field(description="Sealed predecessor package id in the lineage."),
    ]
    package_revision: Annotated[
        int,
        Field(description="Sealed monotonic revision within the lineage."),
    ]
    draft_hash: Annotated[
        str,
        Field(description="Stable content hash of the draft and evidence."),
    ]
    request_id: Annotated[
        str | None,
        Field(
            description="Sealed caller retry-fencing identity, when the request carried one."
        ),
    ]
    source_set_hash: Annotated[
        str | None,
        Field(description="Deterministic source-set hash for compact provenance."),
    ]
    compaction_policy_version: Annotated[
        str | None,
        Field(description="Compaction policy version that stored this artifact."),
    ]
    compact_generation_revision: Annotated[
        int | None,
        Field(description="Compact generation revision of the stored artifact."),
    ]
    generated_at: Annotated[
        AwareTimestamp | None,
        Field(description="Generation timestamp of the stored artifact."),
    ]
    deduplicated: Annotated[
        bool,
        Field(description="Whether this response reports duplicate reuse."),
    ]
    markdown_body: Annotated[
        str,
        Field(description="Canonical linted Markdown body of the package."),
    ]

    @classmethod
    def from_view(
        cls,
        view: ResumePackageView,
        *,
        deduplicated: bool,
    ) -> MemoryResumePackageResponse:
        """Create response from a reopened structured package view.

        Args:
            view: Structured resume package view.
            deduplicated: Whether this response reports duplicate reuse.

        Returns:
            Public resume package response schema.
        """
        return cls(
            package_id=view.package_id,
            project=view.project,
            status=view.status,
            covered_from=view.covered_from,
            covered_to=view.covered_to,
            goal=view.goal,
            summary=view.summary,
            current_state=view.current_state,
            next_single_action=view.next_single_action,
            accepted_changes=[
                MemoryResumePackageAttributionRequest(
                    text=item.text,
                    source_context_id=item.source_context_id,
                )
                for item in view.accepted_changes
            ],
            constraints=[
                MemoryResumePackageAttributionRequest(
                    text=item.text,
                    source_context_id=item.source_context_id,
                )
                for item in view.constraints
            ],
            verified_complete=list(view.verified_complete),
            implemented_unverified=list(view.implemented_unverified),
            unfinished_tasks=list(view.unfinished_tasks),
            uncertain_results=list(view.uncertain_results),
            blockers=list(view.blockers),
            evidence_refs=[
                MemoryResumePackageEvidenceRefResponse.from_view(evidence_ref)
                for evidence_ref in view.evidence_refs
            ],
            lineage_id=view.lineage.lineage_id,
            worker_id=view.lineage.worker_id,
            run_id=view.lineage.run_id,
            workspace_id=view.lineage.workspace_id,
            session_id=view.lineage.session_id,
            previous_package_id=view.lineage.previous_package_id,
            package_revision=_sealed_revision(view),
            draft_hash=view.draft_hash,
            request_id=view.request_id,
            source_set_hash=view.source_set_hash,
            compaction_policy_version=view.compaction_policy_version,
            compact_generation_revision=view.compact_generation_revision,
            generated_at=view.generated_at,
            deduplicated=deduplicated,
            markdown_body=view.markdown_body,
        )


def _sealed_revision(view: ResumePackageView) -> int:
    """Return the sealed revision of a reopened package view.

    Args:
        view: Structured resume package view.

    Returns:
        Sealed monotonic revision.

    Raises:
        ValueError: When a stored canonical package lacks its sealed revision.
    """
    if view.lineage.package_revision is None:
        raise ValueError(
            f"Stored resume package is missing its sealed revision: {view.package_id}"
        )
    return view.lineage.package_revision
