"""HTTP contracts for the high-level Obsidian relate operation."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator

from app.obsidian.domain.contracts.obsidian_relation_contracts import (
    ObsidianRelateRequest,
)
from app.obsidian.domain.entities.obsidian_relation import (
    ObsidianRelateIssue,
    ObsidianRelateResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianRelationType,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class ObsidianRelateRequestSchema(StrictSchemaModel):
    """Request to link two existing managed note identities."""

    source_note_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Existing source note identifier for this relate request."),
    ]
    target_note_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Existing target note identifier for this relate request."),
    ]
    relation: Annotated[
        ObsidianRelationType,
        described_field("Typed frontmatter relation for this relate request."),
    ]
    idempotency_key: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Replay key for this relate request."),
    ]
    expected_source_hash: Annotated[
        str | None,
        StringConstraints(
            strict=True,
            min_length=64,
            max_length=64,
            pattern="^[0-9a-fA-F]{64}$",
        ),
        described_field("Optional source content hash compare-and-swap token."),
    ] = None

    @field_validator("idempotency_key", mode="after")
    @classmethod
    def reject_blank_idempotency_key(cls, value: str) -> str:
        """Reject whitespace-only replay keys at the transport boundary."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be blank")
        return normalized

    def to_command(self) -> ObsidianRelateRequest:
        """Convert validated transport input to the internal command."""
        return ObsidianRelateRequest(
            source_note_id=self.source_note_id,
            target_note_id=self.target_note_id,
            relation=ObsidianRelationType(self.relation),
            idempotency_key=self.idempotency_key,
            expected_source_hash=(
                None
                if self.expected_source_hash is None
                else self.expected_source_hash.lower()
            ),
        )


class ObsidianRelateIssueResponse(StrictSchemaModel):
    """Actionable warning or failure evidence for one relation layer."""

    code: Annotated[str, described_field("Stable issue code for this relate response.")]
    cause: Annotated[str, described_field("Cause for this relate response issue.")]
    affected_capability: Annotated[
        str,
        described_field("Affected capability for this relate response issue."),
    ]
    retryable: Annotated[
        bool,
        described_field("Whether replay is safe for this relate response issue."),
    ]
    safe_next_action: Annotated[
        str,
        described_field("Safe next action for this relate response issue."),
    ]
    recovery_run_id: Annotated[
        str | None,
        described_field("Recovery run identifier for this relate response issue."),
    ] = None

    @classmethod
    def from_entity(cls, issue: ObsidianRelateIssue) -> ObsidianRelateIssueResponse:
        """Build a public issue response from the internal typed issue."""
        return cls(
            code=issue.code,
            cause=issue.cause,
            affected_capability=issue.affected_capability,
            retryable=issue.retryable,
            safe_next_action=issue.safe_next_action,
            recovery_run_id=issue.recovery_run_id,
        )


class ObsidianRelateResponse(StrictSchemaModel):
    """Source, projection, and readback evidence for one relation."""

    completion_status: Annotated[
        ObsidianRelateCompletionStatus,
        described_field("Completion status for this relate response."),
    ]
    idempotency_key: Annotated[
        str,
        described_field("Replay key for this relate response."),
    ]
    replayed: Annotated[
        bool,
        described_field("Whether this response reused a durable relation checkpoint."),
    ]
    source_note_id: Annotated[
        str,
        described_field("Source note identifier for this relate response."),
    ]
    target_note_id: Annotated[
        str,
        described_field("Target note identifier for this relate response."),
    ]
    relation: Annotated[
        ObsidianRelationType,
        described_field("Persisted relation for this relate response."),
    ]
    source_path: Annotated[
        str, described_field("Source path for this relate response.")
    ]
    target_path: Annotated[
        str, described_field("Target path for this relate response.")
    ]
    operation: Annotated[
        ObsidianWriteOperation | None,
        described_field("Canonical write operation for this relate response."),
    ]
    content_hash: Annotated[
        str,
        described_field("Current source content hash for this relate response."),
    ]
    storage_status: Annotated[
        str,
        described_field("Canonical storage status for this relate response."),
    ]
    metadata_status: Annotated[
        str,
        described_field("Metadata index status for this relate response."),
    ]
    fts_status: Annotated[
        str,
        described_field("FTS status for this relate response."),
    ]
    graph_edge_index_status: Annotated[
        str,
        described_field("Indexed graph edge status for this relate response."),
    ]
    graph_projection_status: Annotated[
        str,
        described_field("Graph projection status for this relate response."),
    ]
    source_link_verified: Annotated[
        bool,
        described_field("Source Markdown relation readback status."),
    ]
    target_backlink_verified: Annotated[
        bool,
        described_field("Target backlink readback status."),
    ]
    related_notes_verified: Annotated[
        bool,
        described_field("High-level related-note readback status."),
    ]
    graph_edge_id: Annotated[
        str | None,
        described_field("Exact projected edge identifier for this relate response."),
    ] = None
    projection_run_id: Annotated[
        str | None,
        described_field("Graph projection run identifier for this relate response."),
    ] = None
    warnings: Annotated[
        list[ObsidianRelateIssueResponse],
        described_field("Actionable projection warnings for this relate response."),
    ]
    errors: Annotated[
        list[ObsidianRelateIssueResponse],
        described_field("Actionable relation errors for this relate response."),
    ]

    @classmethod
    def from_entity(cls, result: ObsidianRelateResult) -> ObsidianRelateResponse:
        """Build the transport response from the typed application result."""
        return cls(
            completion_status=result.completion_status,
            idempotency_key=result.idempotency_key,
            replayed=result.replayed,
            source_note_id=result.source_note_id,
            target_note_id=result.target_note_id,
            relation=result.relation,
            source_path=result.source_path,
            target_path=result.target_path,
            operation=result.operation,
            content_hash=result.content_hash,
            storage_status=result.storage_status,
            metadata_status=result.metadata_status,
            fts_status=result.fts_status,
            graph_edge_index_status=result.graph_edge_index_status,
            graph_projection_status=result.graph_projection_status,
            source_link_verified=result.source_link_verified,
            target_backlink_verified=result.target_backlink_verified,
            related_notes_verified=result.related_notes_verified,
            graph_edge_id=result.graph_edge_id,
            projection_run_id=result.projection_run_id,
            warnings=[
                ObsidianRelateIssueResponse.from_entity(item)
                for item in result.warnings
            ],
            errors=[
                ObsidianRelateIssueResponse.from_entity(item) for item in result.errors
            ],
        )
