"""Canonical Context mutation port for memory reconciliation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemorySourceReference,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryRelationType


class IMemoryCanonicalMutationGateway(ABC):
    """Mutate canonical Context Markdown without exposing Obsidian details."""

    @abstractmethod
    async def create_context(
        self,
        candidate: MemoryCandidate,
        lifecycle_status: str,
        supersedes_context_id: str | None = None,
        conflict_set_ids: tuple[str, ...] = (),
        relation: MemoryRelationType | None = None,
        related_context_id: str | None = None,
    ) -> str:
        """Create or return one canonical Context and its source-qualified ID.

        Args:
            candidate: Candidate.
            lifecycle_status: Lifecycle status.
            supersedes_context_id: Supersedes context id.
            conflict_set_ids: Conflict set ids.
            relation: Relation.
            related_context_id: Related context id.

        Returns:
            str: Operation result.
        """

    @abstractmethod
    async def merge_evidence(
        self,
        context_id: str,
        evidence: tuple[MemorySourceReference, ...],
    ) -> str:
        """Merge evidence references into one canonical Context idempotently.

        Args:
            context_id: Context id.
            evidence: Evidence.

        Returns:
            str: Operation result.
        """

    @abstractmethod
    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Link a previous Context to its canonical replacement.

        Args:
            context_id: Context id.
            replacement_context_id: Replacement context id.
        """

    @abstractmethod
    async def verify(self, context_id: str) -> bool:
        """Return whether one canonical Context can be read back successfully.

        Args:
            context_id: Context id.

        Returns:
            bool: Operation result.
        """
