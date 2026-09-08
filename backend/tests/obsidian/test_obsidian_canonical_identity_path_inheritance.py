"""Regression tests for canonical report-family path inheritance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import anyio

from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultSourceSnapshot
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


@dataclass(frozen=True)
class _InventoryItem:
    relative_path: str


@dataclass(frozen=True)
class _FakeNote:
    relative_path: str
    frontmatter: dict[str, object]
    project: str
    note_id: str
    index_status: str = "indexed"


class _FakeObsidianService:
    def __init__(self, notes: list[_FakeNote]) -> None:
        self._notes = {note.relative_path: note for note in notes}

    async def inventory_vault(self, _request: object) -> list[_InventoryItem]:
        return [_InventoryItem(relative_path=path) for path in self._notes]

    async def read_note_by_path(self, path: str) -> _FakeNote:
        return self._notes[path]

    async def source_snapshot(self, max_notes: int) -> ObsidianVaultSourceSnapshot:
        return ObsidianVaultSourceSnapshot(
            notes=cast(
                tuple[ObsidianNoteIndex, ...],
                tuple(self._notes.values()),
            ),
            complete=True,
            scanned_paths=min(len(self._notes), max_notes),
        )


def _weekend_note(*, date: str, relative_path: str, note_id: str) -> _FakeNote:
    return _FakeNote(
        relative_path=relative_path,
        frontmatter={
            "report": "Weekend & Holiday Brief v3",
            "date": date,
            "entity": "Market",
            "edition": "sunday_delta",
        },
        project="Evidence Intelligence",
        note_id=note_id,
    )


def _service(notes: list[_FakeNote]) -> ObsidianCanonicalIdentityService:
    store = ObsidianVaultConfigStore(
        default_vault_path="/tmp/alexandria-canonical-identity-test",
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    obsidian_service = cast(ObsidianService, _FakeObsidianService(notes))
    return ObsidianCanonicalIdentityService(
        obsidian_service=obsidian_service,
        vault_config_store=store,
    )


def test_canonical_identity_inherits_latest_family_path_layout() -> None:
    """A new date should inherit the latest canonical family layout, not Daily."""

    async def scenario() -> None:
        service = _service(
            [
                _weekend_note(
                    date="2026-07-19",
                    relative_path=(
                        "Alexandria/Contexts/Projects/Evidence Intelligence/Weekly/"
                        "2026/07/Weekend Brief/Market/WB Market 2026-07-19.md"
                    ),
                    note_id="old-layout",
                ),
                _weekend_note(
                    date="2026-08-02",
                    relative_path=(
                        "Alexandria/Contexts/Projects/Evidence Intelligence/Weekly/"
                        "2026/08/Weekend Brief/Market/"
                        "Evidence Intelligence Weekend Brief Market 2026-08-02.md"
                    ),
                    note_id="current-layout",
                ),
            ]
        )
        result = await service.resolve(
            project="Evidence Intelligence",
            report="Weekend & Holiday Brief v3",
            date="2026-08-08",
            entity="Market",
            edition="saturday_initial",
        )

        assert result.resolution == "NEW_CANONICAL_IDENTITY"
        assert result.canonical_path == (
            "Alexandria/Contexts/Projects/Evidence Intelligence/Weekly/2026/08/"
            "Weekend Brief/Market/"
            "Evidence Intelligence Weekend Brief Market 2026-08-08.md"
        )
        assert "/Daily/" not in result.canonical_path

    anyio.run(scenario)


def test_canonical_identity_inherited_layout_rolls_year_and_month() -> None:
    """Inherited YYYY/MM partitions should follow the requested report date."""

    async def scenario() -> None:
        service = _service(
            [
                _weekend_note(
                    date="2026-12-27",
                    relative_path=(
                        "Alexandria/Contexts/Projects/Evidence Intelligence/Weekly/"
                        "2026/12/Weekend Brief/Market/"
                        "Evidence Intelligence Weekend Brief Market 2026-12-27.md"
                    ),
                    note_id="year-end-layout",
                )
            ]
        )
        result = await service.resolve(
            project="Evidence Intelligence",
            report="Weekend & Holiday Brief v3",
            date="2027-01-02",
            entity="Market",
            edition="saturday_initial",
        )

        assert result.canonical_path == (
            "Alexandria/Contexts/Projects/Evidence Intelligence/Weekly/2027/01/"
            "Weekend Brief/Market/"
            "Evidence Intelligence Weekend Brief Market 2027-01-02.md"
        )

    anyio.run(scenario)
