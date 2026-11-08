"""Obsidian batch-write schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    schema_dict_default,
    schema_list_default,
)
from app.shared.types.extra_types import JSONObject


class ObsidianBatchWriteOperationRequest(StrictSchemaModel):
    """One CAS write operation in a batch."""

    op: Annotated[str, Field(description="Operation type: create or update.")]
    title: Annotated[str, Field(description="Note title.")]
    body: Annotated[str, Field(description="Note body content.")]
    relative_path: Annotated[str, Field(description="Vault-relative path.")]
    note_id: Annotated[str | None, Field(description="Stable note id.")] = None
    expected_content_hash: Annotated[
        str | None, Field(description="CAS content hash for update.")
    ] = None
    frontmatter: Annotated[
        JSONObject, Field(description="Frontmatter key-value pairs.")
    ] = schema_dict_default()


class ObsidianBatchWriteRequest(StrictSchemaModel):
    """Batch CAS write request with independent operations."""

    operations: Annotated[
        list[ObsidianBatchWriteOperationRequest],
        Field(description="Independent per-item write operations."),
    ] = schema_list_default()


class ObsidianBatchWriteItemResult(StrictSchemaModel):
    """Per-item write outcome."""

    relative_path: Annotated[str, Field(description="Vault-relative path.")]
    note_id: Annotated[str | None, Field(description="Stable note id.")] = None
    status: Annotated[str, Field(description="Operation outcome status.")]
    content_hash: Annotated[
        str | None, Field(description="Content hash after write.")
    ] = None
    current_content_hash: Annotated[
        str | None,
        Field(description="Conflicting note content hash to retry CAS against."),
    ] = None
    error: Annotated[str | None, Field(description="Error detail.")] = None


class ObsidianBatchWriteResponse(StrictSchemaModel):
    """Batch write response with per-item CAS results."""

    results: Annotated[
        list[ObsidianBatchWriteItemResult],
        Field(description="Per-item write outcomes in request order."),
    ] = schema_list_default()
    succeeded: Annotated[int, Field(description="Successful write count.")] = 0
    conflicted: Annotated[int, Field(description="CAS conflict count.")] = 0
    failed: Annotated[int, Field(description="Failed item count.")] = 0
