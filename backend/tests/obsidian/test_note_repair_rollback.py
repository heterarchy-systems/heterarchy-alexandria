"""Repair rollback respects canonical source ownership after indexing failure."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import anyio
import pytest

from app.obsidian.application.notes.writing import obsidian_note_persistence
from app.obsidian.application.notes.writing.obsidian_note_repair import (
    ObsidianNoteRepair,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
    ObsidianWriteConflictError,
)


@pytest.mark.parametrize("parse_failure", [False, True])
@pytest.mark.parametrize("external_edit", [False, True])
def test_raw_repair_rollback_preserves_external_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parse_failure: bool,
    external_edit: bool,
) -> None:
    """Rollback restores owned candidates and rejects source drift on either failure path."""
    relative_path = "Alexandria/Notes/Race.md"
    absolute = tmp_path / relative_path
    absolute.parent.mkdir(parents=True)
    original = (
        "---\nid: race\nalexandria_type: job_plan\ntitle: Race\n---\n\nOriginal\n"
    )
    candidate = original.replace("Original", "Candidate")
    foreign = "External editor content\n"
    absolute.write_text(original, encoding="utf-8")

    def fail_after_persist(
        absolute: Path, document: str, *_args: object, **_kwargs: object
    ) -> None:
        atomic_write_markdown(absolute, document)
        if external_edit:
            atomic_write_markdown(absolute, foreign)
        if parse_failure:
            raise ValueError("index parse failed after source publication")
        return None

    async def unexpected_index_error(_error: object) -> None:
        raise AssertionError("rollback does not record a metadata-index error")

    monkeypatch.setattr(
        obsidian_note_persistence, "persist_and_index", fail_after_persist
    )
    repair = ObsidianNoteRepair(
        repository=object(),
        vault_config_store=ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path),
            default_alexandria_root="Alexandria",
            config_path=None,
        ),
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
        record_index_error=unexpected_index_error,
        skill_publication_policy=None,
    )
    expected_error = (
        ObsidianWriteConflictError if external_edit else ObsidianValidationError
    )
    with pytest.raises(expected_error):
        anyio.run(
            partial(
                repair.repair_note_raw,
                path=relative_path,
                expected_content_hash=hash_text(original),
                raw_content=candidate,
            )
        )
    assert absolute.read_text(encoding="utf-8") == (
        foreign if external_edit else original
    )
