"""Canonical Obsidian temporal metadata projection into Context read models."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.integration.obsidian_context_read_mapper import (
    context_record_from_obsidian_note,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)

RECORDED_AT = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)
VALID_FROM = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
VALID_TO = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def test_context_read_projection_preserves_canonical_temporal_metadata() -> None:
    """Canonical temporal frontmatter must survive into retrieval-readable metadata."""
    body = "# Current state\n\nThe current durable state is active."
    content_hash = context_content_hash(body)
    note = ObsidianNote(
        note_id="temporal-projection-context",
        relative_path="Contexts/Temporal Projection Context.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title="Temporal Projection Context",
        status="active",
        tags=("temporal",),
        project="heterarchy-alexandria",
        source="test",
        content_hash=content_hash,
        frontmatter={
            "scope": "PROJECT",
            "project": "heterarchy-alexandria",
            "visibility": "PROJECT",
            "status": "active",
            "content_hash": content_hash,
            "version": 1,
            "context_kind": "MEMORY",
            "created_at": OBSERVED_AT.isoformat(),
            "updated_at": RECORDED_AT.isoformat(),
            "recorded_at": RECORDED_AT.isoformat(),
            "observed_at": OBSERVED_AT.isoformat(),
            "valid_from": VALID_FROM.isoformat(),
            "valid_to": VALID_TO.isoformat(),
        },
        body=body,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(body.encode("utf-8")),
        modified_at=RECORDED_AT,
        indexed_at=RECORDED_AT,
    )

    context = context_record_from_obsidian_note(note)

    assert context.context_metadata["recorded_at"] == RECORDED_AT.isoformat()
    assert context.context_metadata["observed_at"] == OBSERVED_AT.isoformat()
    assert context.context_metadata["valid_from"] == VALID_FROM.isoformat()
    assert context.context_metadata["valid_to"] == VALID_TO.isoformat()
