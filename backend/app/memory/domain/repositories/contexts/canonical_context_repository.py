"""Repository port for canonical Context stores outside the legacy SQL table."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.context_read_models import ContextRecord


class ICanonicalContextRepository(ABC):
    """Read and mutate source-qualified Context records in canonical storage."""

    @abstractmethod
    def owns(self, context_id: str) -> bool:
        """Return whether this repository owns the source-qualified identifier.

        Args:
            context_id: Source-qualified Context identifier.

        Returns:
            True when this repository owns the identifier.
        """

    @abstractmethod
    async def get(self, context_id: str) -> ContextRecord | None:
        """Return a canonical record when this repository owns the identifier.

        Args:
            context_id: Source-qualified Context identifier.

        Returns:
            Canonical read model, or None when absent or not owned.
        """

    @abstractmethod
    async def archive(self, context_id: str) -> ContextRecord:
        """Archive an owned canonical record without deleting its source artifact.

        Args:
            context_id: Source-qualified Context identifier.

        Returns:
            Archived canonical Context read model.
        """

    @abstractmethod
    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> tuple[ContextRecord, ContextRecord]:
        """Link an owned Context to its canonical replacement.

        Args:
            context_id: Source-qualified superseded Context identifier.
            replacement_context_id: Source-qualified replacement Context identifier.

        Returns:
            Superseded and replacement canonical Context read models.
        """
