"""Focused contracts for persisted Obsidian-to-Context projection integrity."""

from __future__ import annotations

from datetime import UTC, datetime

import anyio


from app.memory.application.integration.context_projection_integrity_service import (
    ContextProjectionIntegrityService,
)
from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.repositories.projection_integrity.context_projection_integrity_repository import (
    IContextProjectionIntegrityRepository,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)


class _ProjectionSource:
    """Deterministic indexed-note source fake."""

    def __init__(self, notes: tuple[ObsidianNote, ...], revision: str) -> None:
        self.notes = notes
        self.revision = revision

    async def list_indexed_notes(self) -> tuple[ObsidianNote, ...]:
        return self.notes

    async def projection_source_revision(self) -> str:
        return self.revision


class _ProjectionRepository(IContextProjectionIntegrityRepository):
    """In-memory singleton persistence fake."""

    def __init__(self) -> None:
        self.snapshot: ContextProjectionIntegritySnapshot | None = None

    async def get_latest(self) -> ContextProjectionIntegritySnapshot | None:
        return self.snapshot

    async def replace_latest(
        self, snapshot: ContextProjectionIntegritySnapshot
    ) -> None:
        self.snapshot = snapshot


def _note(
    note_id: str,
    alexandria_type: AlexandriaNoteType,
    frontmatter: dict[str, str],
) -> ObsidianNote:
    """Build one indexed note for projection validation."""
    body = f"# {note_id}\n\nProjection body."
    indexed_at = datetime(2026, 8, 24, tzinfo=UTC)
    return ObsidianNote(
        note_id=note_id,
        relative_path=f"Contexts/{note_id}.md",
        alexandria_type=alexandria_type,
        title=note_id,
        status="active",
        tags=(),
        project="heterarchy-alexandria",
        source="test",
        content_hash="f" * 64,
        frontmatter=frontmatter,
        body=body,
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=len(body.encode("utf-8")),
        modified_at=indexed_at,
        indexed_at=indexed_at,
    )


def test_projection_integrity_refresh_records_mapper_failure_codes() -> None:
    """A canonical Context mapper failure is persisted instead of aborting the full scan."""

    async def scenario() -> None:
        valid = _note(
            "valid-skill",
            AlexandriaNoteType.SKILL,
            {"scope": "GLOBAL"},
        )
        invalid = _note(
            "invalid-context",
            AlexandriaNoteType.CONTEXT,
            {"scope": "GLOBAL", "content_hash": "0" * 64},
        )
        source = _ProjectionSource((valid, invalid), "obsidian-index:2:revision-a")
        repository = _ProjectionRepository()
        service = ContextProjectionIntegrityService(
            source=source,
            repository=repository,
            max_age_seconds=86400,
        )

        snapshot = await service.refresh()

        assert snapshot.scanned_count == 2
        assert snapshot.valid_count == 1
        assert snapshot.invalid_count == 1
        assert [(item.code, item.count) for item in snapshot.failures] == [
            ("INVALID_CONTENT_HASH", 1)
        ]
        assert repository.snapshot == snapshot

    anyio.run(scenario)


def test_projection_integrity_snapshot_detects_source_revision_drift() -> None:
    """Readiness must stale a persisted scan when the indexed-note source changes."""

    async def scenario() -> None:
        source = _ProjectionSource((), "obsidian-index:0:revision-a")
        repository = _ProjectionRepository()
        service = ContextProjectionIntegrityService(
            source=source,
            repository=repository,
            max_age_seconds=86400,
        )
        refreshed = await service.refresh()
        assert refreshed.healthy is True

        source.revision = "obsidian-index:1:revision-b"
        snapshot = await service.snapshot()

        assert snapshot.available is True
        assert snapshot.stale is True
        assert snapshot.source_revision != snapshot.current_source_revision
        assert snapshot.healthy is False

    anyio.run(scenario)


def test_projection_integrity_snapshot_marks_missing_scan_unhealthy() -> None:
    """A service with no persisted full scan cannot report projection readiness."""

    async def scenario() -> None:
        service = ContextProjectionIntegrityService(
            source=_ProjectionSource((), "obsidian-index:0:none"),
            repository=_ProjectionRepository(),
            max_age_seconds=86400,
        )

        snapshot = await service.snapshot()

        assert snapshot.checked is True
        assert snapshot.available is False
        assert snapshot.stale is True
        assert snapshot.healthy is False

    anyio.run(scenario)
