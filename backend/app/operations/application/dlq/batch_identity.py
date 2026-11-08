"""Canonical note-write identity derivation for DLQ batch operations."""

from app.obsidian.application.notes.mutations.receipt_identity import (
    ReceiptIdentityPolicy,
)
from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchWriteOperation,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
)


def batch_operation_identity(operation: BatchWriteOperation) -> tuple[str, str]:
    """Reuse the ordinary note-write identity for one batch operation."""
    payload = ObsidianSaveNote(
        title=operation.title,
        body=operation.body,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        note_id=operation.note_id,
        relative_path=operation.relative_path,
        frontmatter=dict(operation.frontmatter),
        expected_content_hash=operation.expected_content_hash,
    )
    command = ObsidianWriteNote(
        note=payload,
        write_mode=ObsidianWriteMode.UPSERT,
        match_by=ObsidianWriteMatchBy.PATH,
        frontmatter_mode=ObsidianFrontmatterMode.MERGE,
    )
    return ReceiptIdentityPolicy.request_identity(payload, command)
