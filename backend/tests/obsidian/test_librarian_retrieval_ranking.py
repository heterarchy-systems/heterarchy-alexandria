"""Librarian multi-query retrieval ranking regression tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.obsidian.application.librarian.obsidian_librarian_ranking import (
    fuse_librarian_search_hits,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote, ObsidianSearchHit
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)

NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _hit(note_id: str, score: float) -> ObsidianSearchHit:
    note = ObsidianNote(
        note_id=note_id,
        relative_path=f"Alexandria/Contexts/{note_id}.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=note_id,
        status="active",
        tags=("retrieval-quality",),
        project="heterarchy-alexandria",
        source="test",
        content_hash=f"hash-{note_id}",
        frontmatter={},
        body=f"# {note_id}",
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=100,
        modified_at=NOW,
        indexed_at=NOW,
    )
    return ObsidianSearchHit(
        note=note,
        excerpt=note.body,
        score=score,
        chunk_id=f"chunk-{note_id}",
        heading_path=note.title,
    )


def test_librarian_rank_fusion_prefers_repeated_focused_evidence() -> None:
    """Focused variants should be able to outrank one broad-query false positive."""
    noise = _hit("broad-noise", 0.9)
    target = _hit("focused-target", 0.8)

    ranked = fuse_librarian_search_hits(
        ranked_hit_lists=[
            [noise],
            [target],
            [target],
        ],
        limit=1,
    )

    assert [hit.note.note_id for hit in ranked] == ["focused-target"]


def test_librarian_rank_fusion_deduplicates_notes_before_limit() -> None:
    """Repeated note evidence should not consume multiple source-reference slots."""
    target = _hit("target", 0.9)
    secondary = _hit("secondary", 0.8)

    ranked = fuse_librarian_search_hits(
        ranked_hit_lists=[
            [target, secondary],
            [target],
        ],
        limit=2,
    )

    assert [hit.note.note_id for hit in ranked] == ["target", "secondary"]
