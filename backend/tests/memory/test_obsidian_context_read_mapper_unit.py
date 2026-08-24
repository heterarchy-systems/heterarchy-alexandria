"""Unit contracts for Obsidian-to-Context read mapping."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.memory.application.integration.obsidian_context_read_mapper import (
    context_record_from_obsidian_note,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)


def test_non_context_note_derives_context_projection_content_hash() -> None:
    """A foreign note hash must not override generalized Context integrity."""
    body = "# Runtime Seal\n\nVerified."
    indexed_at = datetime(2026, 8, 23, tzinfo=UTC)
    note = ObsidianNote(
        note_id="impl_runtime_seal",
        relative_path="Alexandria/History/Runtime Seal.md",
        alexandria_type=AlexandriaNoteType.IMPLEMENTATION_HISTORY,
        title="Runtime Seal",
        status="active",
        tags=(),
        project="heterarchy-alexandria",
        source=None,
        content_hash="f" * 64,
        frontmatter={"content_hash": "0" * 64},
        body=body,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(body.encode("utf-8")),
        modified_at=indexed_at,
        indexed_at=indexed_at,
    )

    mapped = context_record_from_obsidian_note(note)

    assert mapped.context_metadata["content_hash"] == context_content_hash(body)


@pytest.mark.parametrize(
    (
        "alexandria_type",
        "source_status",
        "project",
        "source_scope",
        "expected_scope",
    ),
    [
        (
            AlexandriaNoteType.IMPLEMENTATION_HISTORY,
            "completed",
            "heterarchy-alexandria",
            "not-a-context-scope",
            ContextScope.PROJECT,
        ),
        (
            AlexandriaNoteType.JOB_PLAN,
            "planned",
            "heterarchy-alexandria",
            "PROJECT",
            ContextScope.PROJECT,
        ),
        (
            AlexandriaNoteType.PROMPT,
            "inactive",
            "Evidence Intelligence",
            "GLOBAL",
            ContextScope.GLOBAL,
        ),
        (
            AlexandriaNoteType.PROMPT,
            "inactive",
            "Evidence Intelligence",
            "SYSTEM",
            ContextScope.PROJECT,
        ),
        (AlexandriaNoteType.SKILL, "SAVED", None, "GLOBAL", ContextScope.GLOBAL),
    ],
)
def test_non_context_note_uses_generalized_projection_identity(
    alexandria_type: AlexandriaNoteType,
    source_status: str,
    project: str | None,
    source_scope: str,
    expected_scope: ContextScope,
) -> None:
    """Foreign note lifecycle and scope fields must not become Context invariants."""
    body = "# Generalized Projection\n\nRecallable source note."
    indexed_at = datetime(2026, 8, 24, tzinfo=UTC)
    note = ObsidianNote(
        note_id=f"projection_{alexandria_type.value}",
        relative_path=f"Alexandria/Projection/{alexandria_type.value}.md",
        alexandria_type=alexandria_type,
        title="Generalized Projection",
        status=source_status,
        tags=(),
        project=project,
        source="projection-test",
        content_hash="f" * 64,
        frontmatter={
            "status": source_status,
            "scope": source_scope,
            "content_hash": "0" * 64,
            "context_kind": "NOT_A_CONTEXT_KIND",
        },
        body=body,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(body.encode("utf-8")),
        modified_at=indexed_at,
        indexed_at=indexed_at,
    )

    mapped = context_record_from_obsidian_note(note)

    assert mapped.scope is expected_scope
    assert mapped.visibility is expected_scope
    assert mapped.context_metadata["lifecycle_status"] == "active"
    assert mapped.context_metadata["source_status"] == source_status
    assert mapped.context_metadata["content_hash"] == context_content_hash(body)


def test_context_note_keeps_fail_closed_content_hash_validation() -> None:
    """Canonical Context notes must still reject a mismatched integrity hash."""
    body = "# Canonical Context\n\nVerified."
    indexed_at = datetime(2026, 8, 23, tzinfo=UTC)
    note = ObsidianNote(
        note_id="ctx_integrity",
        relative_path="Alexandria/Contexts/Integrity.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title="Canonical Context",
        status="active",
        tags=(),
        project="heterarchy-alexandria",
        source=None,
        content_hash="f" * 64,
        frontmatter={
            "scope": "GLOBAL",
            "content_hash": "0" * 64,
        },
        body=body,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(body.encode("utf-8")),
        modified_at=indexed_at,
        indexed_at=indexed_at,
    )

    try:
        context_record_from_obsidian_note(note)
    except ValueError as exc:
        assert str(exc).startswith("INVALID_CONTENT_HASH:")
    else:
        raise AssertionError("Context hash mismatch must fail closed")
