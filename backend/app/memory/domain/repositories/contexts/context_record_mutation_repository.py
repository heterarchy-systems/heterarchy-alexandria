"""Lifecycle and access mutation port for Context records."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.contracts.context_contracts import ContextAccessCreate
from app.memory.domain.entities.context_read_models import ContextRecord


class IContextRecordMutationRepository(ABC):
    """Archive, explicitly remove, and record access for Context records."""

    @abstractmethod
    async def archive(self, context_id: str) -> ContextRecord:
        """Archive one context instead of deleting it.

        Args:
            context_id: Context identifier.

        Returns:
            Archived context read model.
        """

    @abstractmethod
    async def delete(self, context_id: str) -> None:
        """Hard delete one context and dependent rows.

        Args:
            context_id: Context identifier.

        Returns:
            None.
        """

    @abstractmethod
    async def record_access(self, payload: ContextAccessCreate) -> ContextRecord:
        """Record an access event for recall/audit purposes.

        Args:
            payload: Context access event fields.

        Returns:
            Updated context read model.
        """
