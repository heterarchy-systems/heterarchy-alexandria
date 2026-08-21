"""Obsidian report bundle schema contracts."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleOwner,
    ObsidianReportBundleRequest,
    ObsidianReportBundleVerify,
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianReportBundleResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
    ObsidianRelationType,
    ObsidianReportBundleCompletionStatus,
    ObsidianWriteOperation,
)
from app.obsidian.interface.schemas.obsidian.obsidian_note_write_schema import (
    ObsidianSaveNoteRequest,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONObject
from pydantic import StringConstraints


class ObsidianReportBundleSourceRequest(ObsidianSaveNoteRequest):
    """Canonical source payload for one report bundle."""

    alexandria_type: AlexandriaNoteType = AlexandriaNoteType.CONTEXT

    def to_command(self) -> ObsidianSaveNote:
        """Apply generic Context defaults while preserving explicit metadata.

        Returns:
            Result produced by to_command.
        """
        command = super().to_command()
        frontmatter = dict(command.frontmatter)
        project_value = command.project or frontmatter.get("project")
        project = project_value if isinstance(project_value, str) else None
        if command.alexandria_type is AlexandriaNoteType.CONTEXT:
            frontmatter.setdefault("scope", "PROJECT" if project else "GLOBAL")
        return replace(command, project=project, frontmatter=frontmatter)


class ObsidianReportBundleOwnerRequest(StrictSchemaModel):
    """Existing graph owner to link to the report source."""

    path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Path for this Obsidian report bundle owner request."),
    ]
    relation: Annotated[
        ObsidianRelationType,
        described_field("Relation for this Obsidian report bundle owner request."),
    ] = ObsidianRelationType.CONTAINS

    def to_command(self) -> ObsidianReportBundleOwner:
        """Convert to an immutable owner contract.

        Returns:
            Result produced by to_command.
        """
        return ObsidianReportBundleOwner(
            path=self.path,
            relation=ObsidianRelationType(self.relation),
        )


class ObsidianReportBundleVerifyRequest(StrictSchemaModel):
    """Requested post-write verification stages."""

    index_status: Annotated[
        bool,
        described_field("Index status for this Obsidian report bundle verify request."),
    ] = True
    incoming_edges: Annotated[
        bool,
        described_field(
            "Incoming edges for this Obsidian report bundle verify request."
        ),
    ] = True
    duplicates: Annotated[
        bool,
        described_field("Duplicates for this Obsidian report bundle verify request."),
    ] = True

    def to_command(self) -> ObsidianReportBundleVerify:
        """Convert to an immutable verification contract.

        Returns:
            Result produced by to_command.
        """
        return ObsidianReportBundleVerify(
            index_status=self.index_status,
            incoming_edges=self.incoming_edges,
            duplicates=self.duplicates,
        )


class ObsidianReportBundleRequestSchema(StrictSchemaModel):
    """Idempotent Source/Index/Hub operation request."""

    idempotency_key: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=512),
        described_field("Idempotency key for this Obsidian report bundle request."),
    ]
    source: Annotated[
        ObsidianReportBundleSourceRequest,
        described_field("Source for this Obsidian report bundle request."),
    ]
    graph_owners: Annotated[
        list[ObsidianReportBundleOwnerRequest],
        described_field("Graph owners for this Obsidian report bundle request."),
    ] = schema_list_default()
    reindex: Annotated[
        bool, described_field("Reindex for this Obsidian report bundle request.")
    ] = True
    verify: Annotated[
        ObsidianReportBundleVerifyRequest,
        described_field("Verify for this Obsidian report bundle request."),
    ] = ObsidianReportBundleVerifyRequest()

    def to_command(self) -> ObsidianReportBundleRequest:
        """Convert to the application report bundle command.

        Returns:
            Result produced by to_command.
        """
        return ObsidianReportBundleRequest(
            idempotency_key=self.idempotency_key,
            source=self.source.to_command(),
            graph_owners=tuple(owner.to_command() for owner in self.graph_owners),
            reindex=self.reindex,
            verify=self.verify.to_command(),
        )


class ObsidianReportBundleSourceResponse(StrictSchemaModel):
    """Source write result included in a report bundle response."""

    note_id: Annotated[
        str,
        described_field(
            "Note identifier for this Obsidian report bundle source response."
        ),
    ]
    path: Annotated[
        str, described_field("Path for this Obsidian report bundle source response.")
    ]
    operation: Annotated[
        ObsidianWriteOperation,
        described_field("Operation for this Obsidian report bundle source response."),
    ]
    index_status: Annotated[
        ObsidianIndexStatus,
        described_field(
            "Index status for this Obsidian report bundle source response."
        ),
    ]


class ObsidianReportBundleGraphResponse(StrictSchemaModel):
    """Expected and verified incoming graph edges."""

    expected_incoming_edges: Annotated[
        int,
        described_field(
            "Expected incoming edges for this Obsidian report bundle graph response."
        ),
    ]
    verified_incoming_edges: Annotated[
        int,
        described_field(
            "Verified incoming edges for this Obsidian report bundle graph response."
        ),
    ]
    unresolved_links: Annotated[
        list[str],
        described_field(
            "Unresolved links for this Obsidian report bundle graph response."
        ),
    ]


class ObsidianReportBundleResponse(StrictSchemaModel):
    """Checkpointable report bundle completion response."""

    completion_status: Annotated[
        ObsidianReportBundleCompletionStatus,
        described_field("Completion status for this Obsidian report bundle response."),
    ]
    idempotency_key: Annotated[
        str,
        described_field("Idempotency key for this Obsidian report bundle response."),
    ]
    replayed: Annotated[
        bool, described_field("Replayed for this Obsidian report bundle response.")
    ]
    source: Annotated[
        ObsidianReportBundleSourceResponse | None,
        described_field("Source for this Obsidian report bundle response."),
    ]
    owner_operations: Annotated[
        list[ObsidianWriteOperation],
        described_field("Owner operations for this Obsidian report bundle response."),
    ]
    graph: Annotated[
        ObsidianReportBundleGraphResponse,
        described_field("Graph for this Obsidian report bundle response."),
    ]
    duplicates: Annotated[
        list[str],
        described_field("Duplicates for this Obsidian report bundle response."),
    ]
    failed_stage: Annotated[
        str | None,
        described_field("Failed stage for this Obsidian report bundle response."),
    ]
    rollback_performed: Annotated[
        bool,
        described_field("Rollback performed for this Obsidian report bundle response."),
    ]
    errors: Annotated[
        list[JSONObject],
        described_field("Errors for this Obsidian report bundle response."),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianReportBundleResult,
    ) -> ObsidianReportBundleResponse:
        """Create a public response from a report bundle outcome.

        Args:
            result: Value supplied to from_entity.

        Returns:
            Result produced by from_entity.
        """
        source = None
        if result.source is not None:
            source = ObsidianReportBundleSourceResponse(
                note_id=result.source.note.note_id,
                path=result.source.note.relative_path,
                operation=result.source.operation,
                index_status=result.source.note.index_status,
            )
        return cls(
            completion_status=result.completion_status,
            idempotency_key=result.idempotency_key,
            replayed=result.replayed,
            source=source,
            owner_operations=[item.operation for item in result.owner_writes],
            graph=ObsidianReportBundleGraphResponse(
                expected_incoming_edges=result.graph.expected_incoming_edges,
                verified_incoming_edges=result.graph.verified_incoming_edges,
                unresolved_links=list(result.graph.unresolved_links),
            ),
            duplicates=list(result.duplicates),
            failed_stage=result.failed_stage,
            rollback_performed=result.rollback_performed,
            errors=list(result.errors),
        )
