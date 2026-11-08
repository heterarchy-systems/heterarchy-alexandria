"""DB-free contracts for Obsidian compare-and-swap write fencing."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from threading import get_ident

import anyio
import pytest

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_index,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    note_snapshot_payload_from_path,
)
from app.obsidian.application.notes.writing import (
    obsidian_note_persistence as note_persistence,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.obsidian_exceptions import ObsidianWriteConflictError


def test_cas_source_fence_detects_context_frontmatter_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canonical source drift conflicts even when CONTEXT logical content is unchanged."""
    relative_path = "Alexandria/Contexts/context.md"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    source = (
        "---\n"
        "id: ctx-cas\n"
        "alexandria_type: context\n"
        "title: Original\n"
        "scope: GLOBAL\n"
        "status: current\n"
        "---\n\n"
        "# Body\n\n"
        "Stable content\n"
    )
    path.write_text(source, encoding="utf-8")
    snapshot = note_snapshot_payload_from_path(path, relative_path)
    assert snapshot is not None
    indexed = authoritative_note_from_index(snapshot)
    payload = ObsidianSaveNote(
        title="Replacement",
        body="Stable content",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        relative_path=relative_path,
        expected_content_hash=indexed.content_hash,
    )
    loop_thread = get_ident()
    hash_threads: list[int] = []
    source_matches = note_persistence.source_matches_hash

    def observed_hash(*args: object, **kwargs: object) -> bool:
        hash_threads.append(get_ident())
        return source_matches(*args, **kwargs)

    monkeypatch.setattr(note_persistence, "source_matches_hash", observed_hash)

    validate_source = partial(
        note_persistence.validate_expected_source_state,
        payload=payload,
        indexed_note=indexed,
        safe_path=relative_path,
        vault_path=tmp_path,
        alexandria_root="Alexandria",
    )
    anyio.run(validate_source)

    path.write_text(
        source.replace("title: Original", "title: External"), encoding="utf-8"
    )

    with pytest.raises(ObsidianWriteConflictError, match="canonical Markdown changed"):
        anyio.run(validate_source)

    assert hash_threads
    assert all(thread_id != loop_thread for thread_id in hash_threads)
