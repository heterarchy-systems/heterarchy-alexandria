"""DB-free contracts for Obsidian compare-and-swap write fencing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from types import MethodType

import anyio
import pytest

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_index,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    note_snapshot_payload_from_path,
)
from app.obsidian.application.service.notes.obsidian_note_service import (
    ObsidianNoteService,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.obsidian_exceptions import ObsidianWriteConflictError


class _RecordingCoordinator:
    """Record which maintenance lane a save chooses."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, bool]] = []

    @asynccontextmanager
    async def operation(self, name: str, *, wait: bool = False) -> AsyncIterator[None]:
        self.entries.append(("exclusive", name, wait))
        yield

    @asynccontextmanager
    async def write_operation(self, name: str) -> AsyncIterator[None]:
        self.entries.append(("shared", name, False))
        yield


def _service_for_lane(coordinator: _RecordingCoordinator) -> ObsidianNoteService:
    service = object.__new__(ObsidianNoteService)
    service._index_maintenance_coordinator = coordinator

    async def save_stub(
        _self: ObsidianNoteService,
        _payload: ObsidianSaveNote,
        existing_note: ObsidianNote | None = None,
        frontmatter_mode: object | None = None,
    ) -> tuple[ObsidianNote, bool, str | None]:
        del existing_note, frontmatter_mode
        return object(), True, None  # type: ignore[return-value]

    service._save_note_serialized = MethodType(save_stub, service)  # type: ignore[method-assign]
    return service


@pytest.mark.parametrize(
    ("expected_content_hash", "expected_lane", "expected_operation", "wait"),
    [
        (None, "shared", "obsidian_note_write", False),
        ("a" * 64, "exclusive", "obsidian_note_compare_and_swap", True),
    ],
)
def test_save_note_selects_cas_exclusive_lane(
    expected_content_hash: str | None,
    expected_lane: str,
    expected_operation: str,
    wait: bool,
) -> None:
    """CAS writes serialize; ordinary independent writes keep the shared lane."""
    coordinator = _RecordingCoordinator()
    service = _service_for_lane(coordinator)
    payload = ObsidianSaveNote(
        title="Plan",
        body="Body",
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        expected_content_hash=expected_content_hash,
    )

    anyio.run(service.save_note, payload)

    assert coordinator.entries == [(expected_lane, expected_operation, wait)]


def test_cas_source_fence_detects_context_frontmatter_drift(tmp_path: Path) -> None:
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
    service = object.__new__(ObsidianNoteService)

    validate_source = partial(
        service._validate_expected_source_state,
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
