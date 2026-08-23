"""Typed contract shared by Obsidian note-index compute adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
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


class NoteIndexComputeProvider(ABC):
    """Compute deterministic document fields without owning persistence policy."""

    @abstractmethod
    def compute(self, text: str, relative_path: str) -> NoteIndexComputeResult:
        """Compute normalized note-index fields.

        Args:
            text: Complete Markdown source.
            relative_path: Vault-relative path used for title fallback.

        Returns:
            Deterministic note-index compute result.
        """
