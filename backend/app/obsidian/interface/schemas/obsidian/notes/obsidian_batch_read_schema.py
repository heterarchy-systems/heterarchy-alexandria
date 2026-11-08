"""Obsidian batch-read and link-validation schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    schema_list_default,
)


class ObsidianBatchReadSelectorRequest(StrictSchemaModel):
    """One selector in a batch read request."""

    path: Annotated[str | None, Field(description="Vault-relative path selector.")] = (
        None
    )
    note_id: Annotated[str | None, Field(description="Stable note id selector.")] = None


class ObsidianBatchReadRequest(StrictSchemaModel):
    """Batch read request with independent exact selectors."""

    selectors: Annotated[
        list[ObsidianBatchReadSelectorRequest],
        Field(description="Exact per-item selectors; each needs path or note_id."),
    ] = schema_list_default()


class ObsidianBatchReadResponse(StrictSchemaModel):
    """Batch read response with per-item results."""

    items: Annotated[
        list[ObsidianNoteResponse],
        Field(description="Successfully read notes in selector order."),
    ] = schema_list_default()
    errors: Annotated[
        list[dict[str, str | None]],
        Field(description="Per-item errors for selectors that failed."),
    ] = schema_list_default()
    total: Annotated[int, Field(description="Total selectors processed.")]


class ObsidianBatchValidateLinkItem(StrictSchemaModel):
    """Per-item link validation outcome."""

    path: Annotated[str | None, Field(description="Vault-relative path.")] = None
    note_id: Annotated[str | None, Field(description="Stable note id.")] = None
    status: Annotated[str, Field(description="validated / parse_error / not_found.")]
    exists: Annotated[bool, Field(description="Whether the note exists.")] = False
    parsed_count: Annotated[int, Field(description="Outgoing edge count.")] = 0
    resolved_count: Annotated[int, Field(description="Resolved edge count.")] = 0
    unresolved_count: Annotated[int, Field(description="Unresolved edge count.")] = 0
    error: Annotated[str | None, Field(description="Per-item failure detail.")] = None


class ObsidianBatchValidateLinksRequest(StrictSchemaModel):
    """Batch outgoing-link validation request with exact selectors."""

    selectors: Annotated[
        list[ObsidianBatchReadSelectorRequest],
        Field(description="Exact per-item selectors; each needs path or note_id."),
    ] = schema_list_default()


class ObsidianBatchValidateLinksResponse(StrictSchemaModel):
    """Batch link validation response."""

    items: Annotated[
        list[ObsidianBatchValidateLinkItem],
        Field(description="Per-item validation outcomes."),
    ] = schema_list_default()
