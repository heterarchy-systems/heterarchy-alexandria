"""Shared bounds for canonical Obsidian source scans."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SOURCE_SCAN_LIMIT = 4096
DEFAULT_SOURCE_SCAN_MAX_ENTRIES = 10_000
DEFAULT_SOURCE_SCAN_MAX_TOTAL_BYTES = 64 * 1024 * 1024
DEFAULT_SOURCE_SCAN_MAX_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_SOURCE_SCAN_MAX_ERRORS = 32


@dataclass(frozen=True, slots=True)
class ObsidianSourceScanPolicy:
    """Bound one observation of the managed Markdown source tree."""

    max_notes: int = DEFAULT_SOURCE_SCAN_LIMIT
    max_entries: int = DEFAULT_SOURCE_SCAN_MAX_ENTRIES
    max_total_bytes: int = DEFAULT_SOURCE_SCAN_MAX_TOTAL_BYTES
    max_file_bytes: int = DEFAULT_SOURCE_SCAN_MAX_FILE_BYTES
    max_errors: int = DEFAULT_SOURCE_SCAN_MAX_ERRORS

    def __post_init__(self) -> None:
        """Require every source scan ceiling to be positive."""
        if (
            min(
                self.max_notes,
                self.max_entries,
                self.max_total_bytes,
                self.max_file_bytes,
                self.max_errors,
            )
            <= 0
        ):
            raise ValueError("source scan limits must be greater than zero")


DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY = ObsidianSourceScanPolicy()
