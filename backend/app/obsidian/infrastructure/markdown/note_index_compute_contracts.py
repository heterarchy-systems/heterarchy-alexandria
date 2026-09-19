"""Typed contract shared by Obsidian note-index compute adapters."""

from __future__ import annotations

from dataclasses import dataclass

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianChunkIndex
from app.obsidian.infrastructure.markdown.frontmatter import FrontmatterValue


@dataclass(frozen=True, slots=True)
class NoteIndexComputeResult:
    """Deterministic document compute consumed by Python-owned index policy."""

    frontmatter: dict[str, FrontmatterValue]
    body: str
    title: str
    content_hash: str
    chunks: tuple[ObsidianChunkIndex, ...]
