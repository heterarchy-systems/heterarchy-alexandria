"""Obsidian raw-source and repair schema contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from app.obsidian.domain.entities.obsidian_note import (
    ObsidianFrontmatterRepairResult,
    ObsidianNoteRawRead,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.types.extra_types import JSONObject

if TYPE_CHECKING:
    from app.obsidian.application.notes.writing.obsidian_note_body_patch import (
        ObsidianNoteBodyPatchResult,
    )


class ObsidianNoteRepairRequest(StrictSchemaModel):
    """Bounded raw-source repair for one malformed or damaged note."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=400),
        Field(description="Vault-relative path for this note repair request."),
    ]
    expected_content_hash: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        Field(description="Expected content hash for this note repair request."),
    ]
    raw_content: Annotated[
        str,
        StringConstraints(strict=True, min_length=1),
        Field(description="Full replacement Markdown source for this repair."),
    ]


class ObsidianBodyPatchReplacementRequest(StrictSchemaModel):
    """One exact caller-authored body span replacement."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    old_text: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=4096),
        Field(description="Unique exact text to match once inside the Markdown body."),
    ]
    new_text: Annotated[
        str,
        StringConstraints(strict=True, max_length=4096),
        Field(description="Replacement text for the matched body span; empty deletes."),
    ]


class ObsidianBodyPatchRequest(StrictSchemaModel):
    """CAS-protected bounded body patch; canonical source stays server-owned."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=400),
        Field(description="Vault-relative path for the managed Markdown note."),
    ]
    expected_content_hash: Annotated[
        str,
        StringConstraints(
            strict=True,
            min_length=64,
            max_length=64,
            pattern=r"^[0-9a-fA-F]+$",
        ),
        Field(description="Expected raw-source SHA-256 compare-and-swap token."),
    ]
    replacements: Annotated[
        list[ObsidianBodyPatchReplacementRequest],
        Field(min_length=1, max_length=8),
        Field(description="One to eight unique exact body replacements."),
    ]


class ObsidianNoteRawReadResponse(StrictSchemaModel):
    """Raw malformed-note read response for operator repair inspection."""

    relative_path: Annotated[
        str, Field(description="Path for this Obsidian note raw read response.")
    ]
    raw_text: Annotated[
        str | None,
        Field(description="Raw text for this Obsidian note raw read response."),
    ]
    content_hash: Annotated[
        str | None,
        Field(description="Content hash for this Obsidian note raw read response."),
    ]
    byte_length: Annotated[
        int | None,
        Field(description="Byte length for this Obsidian note raw read response."),
    ]
    parse_status: Annotated[
        str,
        Field(description="Parse status for this Obsidian note raw read response."),
    ]
    parse_error: Annotated[
        str | None,
        Field(description="Parse error for this Obsidian note raw read response."),
    ]
    frontmatter: Annotated[
        JSONObject | None,
        Field(description="Frontmatter for this Obsidian note raw read response."),
    ]
    body: Annotated[
        str | None, Field(description="Body for this Obsidian note raw read response.")
    ]
    note_id: Annotated[
        str | None,
        Field(description="Note id for this Obsidian note raw read response."),
    ]
    index_status: Annotated[
        str | None,
        Field(description="Index status for this Obsidian note raw read response."),
    ]
    byte_exact: Annotated[
        bool,
        Field(
            description="Whether raw_text is the exact durable source bytes rather than "
            "a suppressed or masked view."
        ),
    ] = True

    @classmethod
    def from_entity(cls, read: ObsidianNoteRawRead) -> ObsidianNoteRawReadResponse:
        """Create schema from entity.

        Args:
            read: Domain raw read entity.

        Returns:
            HTTP response schema.
        """
        return cls(
            relative_path=read.relative_path,
            raw_text=read.raw_text,
            content_hash=read.content_hash,
            byte_length=read.byte_length,
            parse_status=read.parse_status,
            parse_error=read.parse_error,
            frontmatter=read.frontmatter,
            body=read.body,
            note_id=read.note_id,
            index_status=read.index_status,
            byte_exact=read.byte_exact,
        )


class ObsidianFrontmatterRepairRequest(StrictSchemaModel):
    """Byte-preserving frontmatter-only repair for one managed note."""

    path: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=400),
        Field(description="Vault-relative path for this frontmatter repair."),
    ]
    expected_content_hash: Annotated[
        str,
        StringConstraints(strict=True, min_length=64, max_length=128),
        Field(description="Current content hash compare-and-swap token."),
    ]
    replacement_frontmatter: Annotated[
        JSONObject,
        Field(
            description="Complete replacement frontmatter mapping; server-owned fields "
            "are rejected when supplied by callers."
        ),
    ]
    preserve_body_bytes: Annotated[
        Literal[True],
        Field(
            description="The body is preserved byte-exact; only the frontmatter block "
            "is replaced. Only True is accepted."
        ),
    ] = True


class ObsidianFrontmatterRepairResponse(StrictSchemaModel):
    """Truthful hash evidence for one byte-preserving frontmatter repair."""

    content_hash_before: Annotated[
        str, Field(description="Canonical content hash before this repair.")
    ]
    content_hash_after: Annotated[
        str, Field(description="Canonical content hash after this repair.")
    ]
    body_hash_before: Annotated[str, Field(description="Body hash before this repair.")]
    body_hash_after: Annotated[str, Field(description="Body hash after this repair.")]
    body_byte_exact_preserved: Annotated[
        bool,
        Field(description="Whether the durable body bytes survived unchanged."),
    ]
    removed_server_owned_fields: Annotated[
        list[str],
        Field(
            description="Server-owned fields removed from the prior source metadata."
        ),
    ]
    parse_status: Annotated[
        str, Field(description="Parse status of the repaired document.")
    ]
    index_status: Annotated[
        str, Field(description="Index status after the repair write.")
    ]
    note_id: Annotated[str, Field(description="Canonical note identifier.")]
    relative_path: Annotated[str, Field(description="Canonical managed note path.")]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianFrontmatterRepairResult,
    ) -> ObsidianFrontmatterRepairResponse:
        """Create the schema from the domain repair evidence."""
        return cls(
            content_hash_before=result.content_hash_before,
            content_hash_after=result.content_hash_after,
            body_hash_before=result.body_hash_before,
            body_hash_after=result.body_hash_after,
            body_byte_exact_preserved=result.body_byte_exact_preserved,
            removed_server_owned_fields=list(result.removed_server_owned_fields),
            parse_status=result.parse_status,
            index_status=result.index_status,
            note_id=result.note_id,
            relative_path=result.relative_path,
        )


class ObsidianBodyPatchResponse(StrictSchemaModel):
    """Secret-free source and index evidence after a bounded body patch."""

    relative_path: Annotated[
        str, Field(description="Canonical vault-relative source path.")
    ]
    note_id: Annotated[str, Field(description="Stable Alexandria note identifier.")]
    content_hash_before: Annotated[
        str, Field(description="Raw source hash before the patch.")
    ]
    content_hash_after: Annotated[
        str, Field(description="Raw source hash after the patch.")
    ]
    index_status: Annotated[
        ObsidianIndexStatus, Field(description="Index status after persistence.")
    ]
    body_replacement_count: Annotated[
        int, Field(description="Number of exact body spans replaced.")
    ]
    changed_span_count: Annotated[
        int,
        Field(
            description="Body spans plus the managed Context hash scalar, when updated."
        ),
    ]
    managed_content_hash_updated: Annotated[
        bool,
        Field(description="Whether the server refreshed the Context body hash."),
    ]
    source_persisted: Annotated[
        bool, Field(description="Whether candidate source bytes were read back.")
    ]
    untouched_source_bytes_preserved: Annotated[
        bool,
        Field(
            description="Whether all bytes outside the requested spans and managed hash scalar "
            "were preserved exactly."
        ),
    ]

    @classmethod
    def from_entity(
        cls,
        result: ObsidianNoteBodyPatchResult,
    ) -> ObsidianBodyPatchResponse:
        """Map verified application evidence to the HTTP response."""
        return cls(
            relative_path=result.relative_path,
            note_id=result.note_id,
            content_hash_before=result.content_hash_before,
            content_hash_after=result.content_hash_after,
            index_status=result.index_status,
            body_replacement_count=result.body_replacement_count,
            changed_span_count=result.changed_span_count,
            managed_content_hash_updated=result.managed_content_hash_updated,
            source_persisted=result.source_persisted,
            untouched_source_bytes_preserved=result.untouched_source_bytes_preserved,
        )
