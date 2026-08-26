"""Narrow source port for Obsidian-to-Context projection integrity scans."""

from __future__ import annotations

from typing import Protocol

from app.obsidian.domain.entities.obsidian_note import ObsidianNote


# protocol-contract: structural-seam
class ContextProjectionIntegritySourcePort(Protocol):
    """Read only the indexed-note data needed by projection integrity."""

    async def list_indexed_notes(self) -> tuple[ObsidianNote, ...]:
        """Return all currently indexed managed notes in deterministic order.

        Returns:
            Immutable indexed-note sequence ordered for repeatable integrity scans.
        """

    async def projection_source_revision(self) -> str:
        """Return the current indexed-note revision token.

        Returns:
            Deterministic revision token for the indexed projection source.
        """
