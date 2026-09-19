"""Parity and boundary contracts for source index and identity snapshots."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_index,
    authoritative_note_from_path,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    note_index_from_path,
    note_snapshot_payload_from_path,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType


def _write_source(
    tmp_path: Path,
    relative_path: str,
    frontmatter: str,
    body: str,
) -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n\n{body}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("relative_path", "frontmatter", "body", "note_type", "title"),
    [
        (
            "Alexandria/Contexts/コンテキスト.md",
            "id: ctx-unicode\n"
            "alexandria_type: context\n"
            "title: コンテキスト\n"
            "scope: GLOBAL\n"
            "status: current\n",
            "# コンテキスト\n\n本文",
            AlexandriaNoteType.CONTEXT,
            "コンテキスト",
        ),
        (
            "Alexandria/Notes/ユニコード.md",
            "id: job-unicode\n"
            "alexandria_type: job_plan\n"
            "status: reviewed\n"
            "project: プロジェクト\n"
            "tags:\n"
            "  - alpha\n"
            "  - ベータ\n"
            "related: Targets/Target.md\n",
            "See [[Target]].",
            AlexandriaNoteType.JOB_PLAN,
            "ユニコード",
        ),
    ],
)
def test_real_native_snapshot_matches_full_source_mapping(
    tmp_path: Path,
    relative_path: str,
    frontmatter: str,
    body: str,
    note_type: AlexandriaNoteType,
    title: str,
) -> None:
    """Full indexing and snapshots share every normalized source field."""
    path = _write_source(tmp_path, relative_path, frontmatter, body)

    full = note_index_from_path(path, relative_path, alexandria_root="Alexandria")
    snapshot = note_snapshot_payload_from_path(path, relative_path)

    assert full is not None
    assert snapshot is not None
    assert full.alexandria_type is note_type
    assert full.title == title
    assert replace(full, chunks=(), edges=()) == snapshot
    assert full.chunks
    assert snapshot.chunks == ()
    assert snapshot.edges == ()
    assert authoritative_note_from_path(
        tmp_path, relative_path, "Alexandria"
    ) == authoritative_note_from_index(full)
    if note_type is AlexandriaNoteType.JOB_PLAN:
        assert full.edges


@pytest.mark.parametrize(
    "frontmatter",
    [
        "alexandria_type: job_plan\ntitle: Missing Id\n",
        "id: invalid-type\nalexandria_type: invalid\n",
    ],
    ids=["missing-id", "invalid-type"],
)
def test_real_native_full_and_snapshot_reject_invalid_managed_frontmatter(
    tmp_path: Path,
    frontmatter: str,
) -> None:
    """Both source modes preserve the same managed id/type failures."""
    path = _write_source(tmp_path, "Alexandria/Notes/Invalid.md", frontmatter, "body")
    relative_path = "Alexandria/Notes/Invalid.md"

    for build in (
        lambda: note_index_from_path(path, relative_path, alexandria_root="Alexandria"),
        lambda: note_snapshot_payload_from_path(path, relative_path),
    ):
        with pytest.raises(ValueError, match="FRONTMATTER_PARSE_ERROR"):
            build()


def test_real_native_full_and_snapshot_reject_secret_frontmatter(
    tmp_path: Path,
) -> None:
    """Secret-like source metadata is rejected before either native mode."""
    relative_path = "Alexandria/Notes/Secret.md"
    path = _write_source(
        tmp_path,
        relative_path,
        "id: secret-note\nalexandria_type: job_plan\ntoken: secret-value\n",
        "body",
    )

    for build in (
        lambda: note_index_from_path(path, relative_path, alexandria_root="Alexandria"),
        lambda: note_snapshot_payload_from_path(path, relative_path),
    ):
        with pytest.raises(ValueError, match="FRONTMATTER_SECRET_DETECTED"):
            build()


def test_real_native_full_and_snapshot_enforce_source_byte_limit(
    tmp_path: Path,
) -> None:
    """Bounded source reads fail consistently before native parsing."""
    relative_path = "Alexandria/Notes/Oversized.md"
    source = "---\nid: oversized\nalexandria_type: job_plan\n---\n\nbody\n"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    max_source_bytes = len(source.encode("utf-8")) - 1

    for build in (
        lambda: note_index_from_path(
            path,
            relative_path,
            alexandria_root="Alexandria",
            max_source_bytes=max_source_bytes,
        ),
        lambda: note_snapshot_payload_from_path(
            path, relative_path, max_source_bytes=max_source_bytes
        ),
    ):
        with pytest.raises(ValueError, match="SOURCE_SCAN_LIMIT_EXCEEDED"):
            build()
