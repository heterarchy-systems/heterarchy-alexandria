"""Pydantic schemas for librarian brief preview endpoints."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.librarian.domain.entities.budget_policy import BudgetPolicy
from app.librarian.domain.entities.context_pack_compact import ContextPackCompact
from app.librarian.domain.entities.source_ref import SourceRef
from app.librarian.domain.event_enum.source_ref_enums import SourceRefType
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)


class SourceRefSchema(StrictSchemaModel):
    """I/O schema for a lazy-load source reference."""

    source_type: Annotated[
        SourceRefType, described_field("Source type for this source ref.")
    ]
    source_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Source identifier for this source ref."),
    ]
    title: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Title for this source ref."),
    ]
    detail_path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Detail path for this source ref."),
    ]
    preview: Annotated[str | None, described_field("Preview for this source ref.")] = (
        None
    )

    def to_entity(self) -> SourceRef:
        """Convert schema to domain entity.

        Returns:
            Source reference domain entity.
        """
        return SourceRef(
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            detail_path=self.detail_path,
            preview=self.preview,
        )


class BudgetPolicySchema(StrictSchemaModel):
    """I/O schema for packet budget policy."""

    max_input_chars: Annotated[
        int, described_field("Max input chars for this budget policy.", ge=1)
    ] = 12000
    max_source_refs: Annotated[
        int, described_field("Max source refs for this budget policy.", ge=1, le=100)
    ] = 20
    max_preview_chars: Annotated[
        int, described_field("Max preview chars for this budget policy.", ge=1)
    ] = 800

    def to_entity(self) -> BudgetPolicy:
        """Convert schema to domain entity.

        Returns:
            Budget policy domain entity.
        """
        return BudgetPolicy(
            max_input_chars=self.max_input_chars,
            max_source_refs=self.max_source_refs,
            max_preview_chars=self.max_preview_chars,
        )


class ContextPackCompactSchema(StrictSchemaModel):
    """I/O schema for compact context supplied to the compiler."""

    markdown_body: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Markdown body for this context pack compact."),
    ]
    source_refs: Annotated[
        list[SourceRefSchema],
        described_field("Source refs for this context pack compact."),
    ] = schema_list_default()

    def to_entity(self) -> ContextPackCompact:
        """Convert schema to domain entity.

        Returns:
            Context-pack compact domain entity.
        """
        return ContextPackCompact(
            markdown_body=self.markdown_body,
            source_refs=tuple(
                source_ref.to_entity() for source_ref in self.source_refs
            ),
        )


class LibrarianBriefPreviewRequest(StrictSchemaModel):
    """Request to compile a preview knowledge packet."""

    prompt: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        described_field("Prompt for this librarian brief preview request."),
    ]
    project: Annotated[
        str | None, described_field("Project for this librarian brief preview request.")
    ] = None
    budget: Annotated[
        BudgetPolicySchema,
        described_field("Budget for this librarian brief preview request."),
    ] = BudgetPolicySchema()
    context_compact: Annotated[
        ContextPackCompactSchema | None,
        described_field("Context compact for this librarian brief preview request."),
    ] = None
    source_refs: Annotated[
        list[SourceRefSchema],
        described_field("Source refs for this librarian brief preview request."),
    ] = schema_list_default()


class LibrarianBriefPreviewResponse(StrictSchemaModel):
    """Compiled librarian brief preview response."""

    prompt: Annotated[
        str, described_field("Prompt for this librarian brief preview response.")
    ]
    project: Annotated[
        str | None,
        described_field("Project for this librarian brief preview response."),
    ]
    packet_markdown: Annotated[
        str,
        described_field("Packet markdown for this librarian brief preview response."),
    ]
    source_refs: Annotated[
        list[SourceRefSchema],
        described_field("Source refs for this librarian brief preview response."),
    ]
    budget_policy: Annotated[
        BudgetPolicySchema,
        described_field("Budget policy for this librarian brief preview response."),
    ]
