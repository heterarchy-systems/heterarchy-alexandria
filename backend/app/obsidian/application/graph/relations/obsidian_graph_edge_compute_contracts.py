"""Typed edge-compute contract for Obsidian note indexing."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianEdgeIndex
from app.shared.types.extra_types import JSONObject


class ObsidianGraphEdgeComputeProvider(ABC):
    """Compute deterministic edge indexes under Python-owned relation policy."""

    @abstractmethod
    def build(
        self,
        note_id: str,
        relative_path: str,
        alexandria_root: str,
        frontmatter: JSONObject,
        body: str,
    ) -> list[ObsidianEdgeIndex]:
        """Build note edges.

        Args:
            note_id: Stable source note identity.
            relative_path: Vault-relative source path.
            alexandria_root: Managed Alexandria root.
            frontmatter: Normalized note frontmatter.
            body: Normalized Markdown body.

        Returns:
            Deterministic edge indexes.
        """
