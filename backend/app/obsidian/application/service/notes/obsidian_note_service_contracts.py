"""Application contracts used by the canonical Obsidian note service."""

from __future__ import annotations

from typing import Protocol


# protocol-contract: structural-seam
class ObsidianNoteSupersedeHook(Protocol):
    """Reconcile Context supersede metadata after a canonical save."""

    async def __call__(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Mark one Context as superseded.

        Args:
            superseded_context_id: Context being replaced.
            replacement_context_id: Canonical replacement Context.
        """
