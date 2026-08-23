"""Cross-platform Unicode path identity contracts for Obsidian indexing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
    validate_context_reindex_manifest,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.paths import canonical_relative_path


def _candidate(
    *,
    physical_path: str,
    logical_path: str,
    note_id: str,
    content_hash: str,
) -> ContextReindexCandidate:
    """Create one minimal managed-note candidate for path identity tests.

    Args:
        physical_path: Physical filesystem-relative test path.
        logical_path: Alexandria logical relative path.
        note_id: Stable note identity.
        content_hash: Deterministic content hash.

    Returns:
        Candidate accepted by the reindex manifest validator.
    """
    return ContextReindexCandidate(
        path=Path(physical_path),
        payload=ObsidianNoteIndex(
            note_id=note_id,
            relative_path=logical_path,
            alexandria_type=AlexandriaNoteType.CONTEXT,
            title=logical_path,
            status="active",
            tags=(),
            project=None,
            source="test",
            content_hash=content_hash,
            frontmatter={"scope": "GLOBAL"},
            body="test",
            size_bytes=4,
            modified_at=datetime(2026, 1, 1, tzinfo=UTC),
            chunks=(),
        ),
    )


def test_canonical_relative_path_normalizes_separators_and_unicode_to_nfc() -> None:
    """Normalize Windows separators and decomposed Unicode into one logical path."""
    assert canonical_relative_path("Contexts\\기능\\Cafe\u0301.md") == (
        "Contexts/기능/Café.md"
    )


def test_canonical_relative_path_preserves_case_sensitive_identity() -> None:
    """Keep Linux-compatible case distinctions while normalizing Unicode form."""
    assert canonical_relative_path("Contexts/File.md") != canonical_relative_path(
        "Contexts/file.md"
    )


def test_manifest_rejects_multiple_physical_paths_for_one_canonical_identity() -> None:
    """Reject NFC/NFD physical duplicates instead of selecting a silent winner."""
    manifest = validate_context_reindex_manifest(
        [
            _candidate(
                physical_path="Contexts/기능/Café.md",
                logical_path="Contexts/기능/Café.md",
                note_id="note-nfc",
                content_hash="a" * 64,
            ),
            _candidate(
                physical_path="Contexts/기능/Cafe\u0301.md",
                logical_path="Contexts/기능/Cafe\u0301.md",
                note_id="note-nfd",
                content_hash="b" * 64,
            ),
        ]
    )

    assert manifest.candidates == ()
    assert len(manifest.issues) == 2
    assert all(
        issue.message.startswith("DUPLICATE_CANONICAL_PATH:")
        for issue in manifest.issues
    )
