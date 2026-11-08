"""Obsidian report bundle schema contracts."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from pydantic import Field, StringConstraints

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
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianSaveNoteRequest,
)
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianPathText,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default
from app.shared.types.extra_types import JSONObject


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
        ObsidianPathText,
        Field(description="Path for this Obsidian report bundle owner request."),
    ]
    relation: Annotated[
        ObsidianRelationType,
        Field(description="Relation for this Obsidian report bundle owner request."),
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
        Field(
            description="Index status for this Obsidian report bundle verify request."
        ),
    ] = True
    incoming_edges: Annotated[
        bool,
        Field(
            description="Incoming edges for this Obsidian report bundle verify request."
        ),
    ] = True
    duplicates: Annotated[
        bool,
        Field(description="Duplicates for this Obsidian report bundle verify request."),
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
        Field(description="Idempotency key for this Obsidian report bundle request."),
    ]
    source: Annotated[
        ObsidianReportBundleSourceRequest,
        Field(description="Source for this Obsidian report bundle request."),
    ]
    graph_owners: Annotated[
        list[ObsidianReportBundleOwnerRequest],
        Field(description="Graph owners for this Obsidian report bundle request."),
    ] = schema_list_default()
    reindex: Annotated[
        bool, Field(description="Reindex for this Obsidian report bundle request.")
    ] = True
    verify: Annotated[
        ObsidianReportBundleVerifyRequest,
        Field(description="Verify for this Obsidian report bundle request."),
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
        Field(
            description="Note identifier for this Obsidian report bundle source response."
        ),
    ]
    path: Annotated[
        str, Field(description="Path for this Obsidian report bundle source response.")
    ]
    operation: Annotated[
        ObsidianWriteOperation,
        Field(description="Operation for this Obsidian report bundle source response."),
    ]
    index_status: Annotated[
        ObsidianIndexStatus,
        Field(
            description="Index status for this Obsidian report bundle source response."
        ),
    ]


class ObsidianReportBundleGraphResponse(StrictSchemaModel):
    """Expected and verified incoming graph edges."""

    expected_incoming_edges: Annotated[
        int,
        Field(
            description="Expected incoming edges for this Obsidian report bundle graph response."
        ),
    ]
    verified_incoming_edges: Annotated[
        int,
        Field(
            description="Verified incoming edges for this Obsidian report bundle graph response."
        ),
    ]
    unresolved_links: Annotated[
        list[str],
        Field(
            description="Unresolved links for this Obsidian report bundle graph response."
        ),
    ]


class ObsidianReportBundleResponse(StrictSchemaModel):
    """Checkpointable report bundle completion response."""

    completion_status: Annotated[
        ObsidianReportBundleCompletionStatus,
        Field(
            description="Completion status for this Obsidian report bundle response."
        ),
    ]
    idempotency_key: Annotated[
        str,
        Field(description="Idempotency key for this Obsidian report bundle response."),
    ]
    replayed: Annotated[
        bool, Field(description="Replayed for this Obsidian report bundle response.")
    ]
    source: Annotated[
        ObsidianReportBundleSourceResponse | None,
        Field(description="Source for this Obsidian report bundle response."),
    ]
    owner_operations: Annotated[
        list[ObsidianWriteOperation],
        Field(description="Owner operations for this Obsidian report bundle response."),
    ]
    graph: Annotated[
        ObsidianReportBundleGraphResponse,
        Field(description="Graph for this Obsidian report bundle response."),
    ]
    duplicates: Annotated[
        list[str],
        Field(description="Duplicates for this Obsidian report bundle response."),
    ]
    failed_stage: Annotated[
        str | None,
        Field(description="Failed stage for this Obsidian report bundle response."),
    ]
    rollback_performed: Annotated[
        bool,
        Field(
            description="Rollback performed for this Obsidian report bundle response."
        ),
    ]
    errors: Annotated[
        list[JSONObject],
        Field(description="Errors for this Obsidian report bundle response."),
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
