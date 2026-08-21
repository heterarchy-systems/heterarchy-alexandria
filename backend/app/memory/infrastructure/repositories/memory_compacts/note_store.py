"""Low-level Obsidian note storage for Memory Compact artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_contracts import (
    NOTE_SUFFIX,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_parser import (
    read_compact_file,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_path_policy import (
    is_safe_note_id,
    resolve_base_dir,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_serializer import (
    serialize_compact,
)


class MemoryCompactNoteStore:
    """Scan, read, atomically write, and delete Memory Compact Markdown notes."""

    def __init__(self, vault_path: str | Path, relative_dir: str | Path) -> None:
        """Create the note store.

        Args:
            vault_path: Obsidian vault root path.
            relative_dir: Relative folder for Memory Compact notes.
        """
        self._base_dir = resolve_base_dir(vault_path, relative_dir)

    def read_all(self) -> list[MemoryCompact]:
        """Read the newest representation of every compact id.

        Returns:
            Deduplicated Memory Compact entities.
        """
        compacts_by_id: dict[str, MemoryCompact] = {}
        for path in self._note_paths():
            compact = read_compact_file(path)
            if compact is None:
                continue
            existing = compacts_by_id.get(compact.id)
            if existing is None or _compact_sort_key(compact) > _compact_sort_key(
                existing
            ):
                compacts_by_id[compact.id] = compact
        return list(compacts_by_id.values())

    def get(self, compact_id: str) -> MemoryCompact | None:
        """Read one compact by stable id.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Matching compact when present.
        """
        return next(
            (compact for compact in self.read_all() if compact.id == compact_id),
            None,
        )

    def write(self, compact: MemoryCompact) -> None:
        """Atomically write one Memory Compact note.

        Args:
            compact: Memory Compact entity to persist.
        """
        existing_paths = self._paths_for_compact_id(compact.id)
        path = self._compact_path(compact.id, created_at=compact.created_at)
        if path is None:
            raise ValueError("Memory Compact id cannot be used as a note filename")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{NOTE_SUFFIX}.tmp")
        temp_path.write_text(serialize_compact(compact), encoding="utf-8")
        temp_path.replace(path)
        for existing_path in existing_paths:
            if existing_path != path and existing_path.exists():
                existing_path.unlink()

    def delete(self, compact_id: str) -> None:
        """Delete one Memory Compact note by stable id.

        Args:
            compact_id: Memory Compact identifier.
        """
        for path in self._paths_for_compact_id(compact_id):
            if path.exists():
                path.unlink()

    def _note_paths(self) -> list[Path]:
        if not self._base_dir.exists():
            return []
        return sorted(self._base_dir.rglob(f"*{NOTE_SUFFIX}"))

    def _compact_path(
        self,
        compact_id: str,
        created_at: datetime | None = None,
    ) -> Path | None:
        if not is_safe_note_id(compact_id):
            return None
        directory = self._base_dir
        if created_at is not None:
            directory = directory / f"{created_at.year:04d}" / f"{created_at.month:02d}"
        return directory / f"{compact_id}{NOTE_SUFFIX}"

    def _paths_for_compact_id(self, compact_id: str) -> list[Path]:
        if not is_safe_note_id(compact_id) or not self._base_dir.exists():
            return []
        matching_paths: list[Path] = []
        for candidate in self._note_paths():
            if candidate.stem == compact_id:
                matching_paths.append(candidate)
                continue
            compact = read_compact_file(candidate)
            if compact is not None and compact.id == compact_id:
                matching_paths.append(candidate)
        return matching_paths


def _compact_sort_key(compact: MemoryCompact) -> tuple[datetime, datetime]:
    return compact.updated_at, compact.created_at
