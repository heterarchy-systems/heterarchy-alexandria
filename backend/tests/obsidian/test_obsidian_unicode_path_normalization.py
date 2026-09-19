"""Cross-platform Unicode path identity contracts for Obsidian indexing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.paths import canonical_relative_path
from app.shared.infrastructure.native_compile_plan import (
    create_native_compile_plan_provider,
)


def _note(
    *,
    relative_path: str,
    note_id: str,
    content_hash: str,
) -> dict[str, Any]:
    """Create one minimal compile input for path identity tests.

    Args:
        relative_path: Alexandria logical relative path.
        note_id: Stable note identity.
        content_hash: Deterministic content hash.

    Returns:
        Compile document wire payload for the context note.
    """
    return {
        "relative_path": relative_path,
        "note_id": note_id,
        "title": relative_path,
        "alexandria_type": "context",
        "status": "active",
        "aliases": [],
        "text": f"---\nid: {note_id}\n---\n\ntest",
        "source_hash": content_hash,
        "body": "test",
        "frontmatter": {"scope": "GLOBAL", "id": note_id},
        "edge_seeds": [],
        "provided_chunks": [
            {"chunk_index": 0, "content_hash": content_hash},
        ],
        "provided_edges": [],
        "manifest_candidate": {
            "note_id": note_id,
            "relative_path": relative_path,
            "canonical_relative_path": canonical_relative_path(relative_path),
            "is_context": True,
            "identity": {
                "scope": "GLOBAL",
                "project": None,
                "workspace_id": None,
                "agent_id": None,
                "user_id": None,
                "session_id": None,
                "content_hash": content_hash,
                "supersedes_context_id": None,
                "superseded_by_context_id": None,
            },
            "supersedes_context_id": None,
            "superseded_by_context_id": None,
        },
    }


def test_canonical_relative_path_normalizes_separators_and_unicode_to_nfc() -> None:
    """Normalize Windows separators and decomposed Unicode into one logical path."""
    assert canonical_relative_path("Contexts\\기능\\Cafe\u0301.md") == (
        "Contexts/기능/Café.md"
    )


def test_canonical_relative_path_preserves_case_sensitive_identity() -> None:
    """Keep Linux-compatible case distinctions while normalizing Unicode form."""
    assert canonical_relative_path("Contexts/File.md") != canonical_relative_path(
        "Contexts/file.md"
    )


def test_compile_authority_rejects_multiple_physical_paths_for_one_canonical_identity() -> (
    None
):
    """Reject NFC/NFD physical duplicates instead of selecting a silent winner."""
    nfc_note = _note(
        relative_path="Contexts/기능/Café.md",
        note_id="note-nfc",
        content_hash="a" * 64,
    )
    nfd_note = _note(
        relative_path="Contexts/기능/Cafe\u0301.md",
        note_id="note-nfd",
        content_hash="b" * 64,
    )
    plan = create_native_compile_plan_provider().compile(
        policy={
            "chunk_max_chars": 600,
            "chunk_overlap_chars": 80,
            "embedding_fingerprint_key": "unicode-path-v1",
        },
        current_documents=[nfc_note, nfd_note],
        previous={
            "embedding_fingerprint_key": "unicode-path-v1",
            "documents": [],
        },
    )

    assert all(not upsert["manifest_accepted"] for upsert in plan["upserts"])
    assert len(plan["diagnostics"]) == 2
    assert all(
        diagnostic["message"].startswith("DUPLICATE_CANONICAL_PATH:")
        for diagnostic in plan["diagnostics"]
    )
