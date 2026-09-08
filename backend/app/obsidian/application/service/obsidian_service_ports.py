"""Source-owned capability ports exposed by the Obsidian application facade."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianReindexResult,
    ObsidianSearchHit,
    ObsidianVaultLocation,
    ObsidianVaultStatus,
)


class ObsidianReadinessPort(ABC):
    """Expose Obsidian vault and index readiness."""

    @abstractmethod
    def vault_location(self) -> ObsidianVaultLocation:
        """Return canonical source location without reading index metadata."""

    @abstractmethod
    async def status(self) -> ObsidianVaultStatus:
        """Return current vault and index status.

        Returns:
            Current Obsidian vault and index status.
        """


class ObsidianDataIntegrityPort(ABC):
    """Expose managed Markdown paths for integrity diagnostics."""

    @abstractmethod
    async def managed_markdown_paths(self) -> list[str]:
        """Return every managed Markdown path regardless of index validity.

        Returns:
            Vault-relative managed Markdown paths.
        """


class ObsidianSearchPort(ABC):
    """Expose indexed Obsidian search to other bounded contexts."""

    @abstractmethod
    async def search(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = False,
    ) -> list[ObsidianSearchHit]:
        """Return indexed Obsidian search results.

        Args:
            query: Structured Obsidian search query.
            refresh: Whether the vault should be refreshed before searching.

        Returns:
            Ranked Obsidian search hits.
        """


class ObsidianReadPort(ABC):
    """Expose canonical Obsidian note reads."""

    @abstractmethod
    async def read_note(self, note_id: str) -> ObsidianNote:
        """Read one managed note by stable identifier.

        Args:
            note_id: Stable note identifier.

        Returns:
            Authoritative managed note.
        """

    @abstractmethod
    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        """Read one managed note by vault-relative path.

        Args:
            relative_path: Vault-relative Markdown path.

        Returns:
            Authoritative managed note.
        """


class ObsidianRecoveryPort(
    ObsidianReadinessPort, ObsidianSearchPort, ObsidianReadPort, ABC
):
    """Expose the Obsidian capabilities required by operational recovery."""

    @abstractmethod
    async def reindex(self) -> ObsidianReindexResult:
        """Rebuild changed Obsidian index rows.

        Returns:
            Obsidian reindex result.
        """


class ObsidianMutationPort(ObsidianReadPort, ABC):
    """Expose canonical Obsidian Context mutation operations."""

    @abstractmethod
    async def save_note(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Create or replace one Alexandria-managed note.

        Args:
            payload: Canonical note save request.

        Returns:
            Saved managed note.
        """

    @abstractmethod
    async def supersede_context(
        self,
        note_id: str,
        replacement_note_id: str,
    ) -> tuple[ObsidianNote, ObsidianNote]:
        """Supersede one canonical Context with an existing replacement.

        Args:
            note_id: Canonical Context note identifier to supersede.
            replacement_note_id: Canonical replacement note identifier.

        Returns:
            Superseded and replacement canonical notes.
        """
