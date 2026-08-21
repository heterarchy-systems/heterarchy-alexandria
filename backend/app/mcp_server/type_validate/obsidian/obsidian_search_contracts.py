"""Typed compact response contracts for Obsidian MCP search."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict

from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class VaultSearchBackendNote(StrictSchemaModel):
    """Validated subset of one backend Obsidian note search payload."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Annotated[
        str, described_field("Stable identifier for this vault search backend note.")
    ]
    alexandria_type: Annotated[
        str, described_field("Alexandria type for this vault search backend note.")
    ]
    path: Annotated[str, described_field("Path for this vault search backend note.")]
    title: Annotated[str, described_field("Title for this vault search backend note.")]
    status: Annotated[
        str, described_field("Status for this vault search backend note.")
    ]
    tags: Annotated[
        list[str], described_field("Tags for this vault search backend note.")
    ] = schema_list_default()
    project: Annotated[
        str | None, described_field("Project for this vault search backend note.")
    ] = None
    content_hash: Annotated[
        str | None, described_field("Content hash for this vault search backend note.")
    ] = None
    index_status: Annotated[
        str | None, described_field("Index status for this vault search backend note.")
    ] = None
    wikilink: Annotated[
        str | None, described_field("Wikilink for this vault search backend note.")
    ] = None


class VaultSearchBackendHit(StrictSchemaModel):
    """Validated backend search hit used by the MCP compaction boundary."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    note: Annotated[
        VaultSearchBackendNote,
        described_field("Note for this vault search backend hit."),
    ]
    excerpt: Annotated[
        str, described_field("Excerpt for this vault search backend hit.")
    ]
    score: Annotated[float, described_field("Score for this vault search backend hit.")]
    chunk_id: Annotated[
        str | None,
        described_field("Chunk identifier for this vault search backend hit."),
    ] = None
    heading_path: Annotated[
        str | None, described_field("Heading path for this vault search backend hit.")
    ] = None


class VaultSearchBackendResponse(StrictSchemaModel):
    """Validated backend search response before MCP compaction."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    items: Annotated[
        list[VaultSearchBackendHit],
        described_field("Items for this vault search backend response."),
    ] = schema_list_default()
    total: Annotated[
        int, described_field("Total for this vault search backend response.")
    ] = 0


class VaultSearchToolNote(StrictSchemaModel):
    """Agent-facing note metadata returned by compact vault search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: Annotated[
        str, described_field("Note identifier for this vault search tool note.")
    ]
    alexandria_type: Annotated[
        str, described_field("Alexandria type for this vault search tool note.")
    ]
    path: Annotated[str, described_field("Path for this vault search tool note.")]
    title: Annotated[str, described_field("Title for this vault search tool note.")]
    status: Annotated[str, described_field("Status for this vault search tool note.")]
    tags: Annotated[
        list[str], described_field("Tags for this vault search tool note.")
    ] = schema_list_default()
    project: Annotated[
        str | None, described_field("Project for this vault search tool note.")
    ] = None
    content_hash: Annotated[
        str | None, described_field("Content hash for this vault search tool note.")
    ] = None
    index_status: Annotated[
        str | None, described_field("Index status for this vault search tool note.")
    ] = None
    wikilink: Annotated[
        str | None, described_field("Wikilink for this vault search tool note.")
    ] = None

    @classmethod
    def from_backend(cls, note: VaultSearchBackendNote) -> VaultSearchToolNote:
        """Create compact agent-facing note metadata.

        Args:
            note: Validated backend note search payload.

        Returns:
            Compact MCP note metadata without body or frontmatter.
        """
        return cls(
            note_id=note.id,
            alexandria_type=note.alexandria_type,
            path=note.path,
            title=note.title,
            status=note.status,
            tags=note.tags,
            project=note.project,
            content_hash=note.content_hash,
            index_status=note.index_status,
            wikilink=note.wikilink,
        )

    def to_payload(self) -> JSONObject:
        """Serialize compact note metadata to the JSON boundary.

        Returns:
            JSON object safe for the MCP response.
        """
        return {
            "note_id": self.note_id,
            "alexandria_type": self.alexandria_type,
            "path": self.path,
            "title": self.title,
            "status": self.status,
            "tags": self.tags,
            "project": self.project,
            "content_hash": self.content_hash,
            "index_status": self.index_status,
            "wikilink": self.wikilink,
        }


class VaultSearchToolHit(StrictSchemaModel):
    """One compact note-level MCP vault search result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    note: Annotated[
        VaultSearchToolNote, described_field("Note for this vault search tool hit.")
    ]
    excerpt: Annotated[str, described_field("Excerpt for this vault search tool hit.")]
    score: Annotated[float, described_field("Score for this vault search tool hit.")]
    chunk_id: Annotated[
        str | None, described_field("Chunk identifier for this vault search tool hit.")
    ] = None
    heading_path: Annotated[
        str | None, described_field("Heading path for this vault search tool hit.")
    ] = None

    @classmethod
    def from_backend(cls, hit: VaultSearchBackendHit) -> VaultSearchToolHit:
        """Create one compact MCP search hit.

        Args:
            hit: Validated backend search hit.

        Returns:
            Compact hit retaining only note metadata and the matched excerpt.
        """
        return cls(
            note=VaultSearchToolNote.from_backend(hit.note),
            excerpt=hit.excerpt,
            score=hit.score,
            chunk_id=hit.chunk_id,
            heading_path=hit.heading_path,
        )

    def to_payload(self) -> JSONObject:
        """Serialize one compact search hit.

        Returns:
            JSON object safe for the MCP response.
        """
        return {
            "note": self.note.to_payload(),
            "excerpt": self.excerpt,
            "score": self.score,
            "chunk_id": self.chunk_id,
            "heading_path": self.heading_path,
        }


def compact_vault_search_response(value: JSONValue) -> JSONObject:
    """Validate and compact one backend vault search response.

    Args:
        value: Raw JSON response returned by the backend search endpoint.

    Returns:
        Note-level MCP response without full Markdown bodies or frontmatter.
    """
    backend = VaultSearchBackendResponse.model_validate(value)
    seen_note_ids: set[str] = set()
    items: list[JSONObject] = []
    for item in backend.items:
        if item.note.id in seen_note_ids:
            continue
        seen_note_ids.add(item.note.id)
        items.append(VaultSearchToolHit.from_backend(item).to_payload())
    return {
        "items": items,
        "total": len(items),
    }
