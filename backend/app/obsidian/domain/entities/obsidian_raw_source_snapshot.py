"""Internal raw Markdown observations used by data-integrity diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ObsidianRawSourceFile:
    """One successfully read managed Markdown source, before parsing."""

    relative_path: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class ObsidianRawSourceSnapshot:
    """Bounded source observation; completeness does not imply atomicity."""

    files: tuple[ObsidianRawSourceFile, ...]
    complete: bool
    total_bytes_read: int
    errors: tuple[str, ...] = field(default_factory=tuple)
