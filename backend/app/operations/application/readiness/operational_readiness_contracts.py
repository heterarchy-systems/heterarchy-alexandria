"""Readiness service protocols required by operational snapshot collection."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus


class ContextReadinessService(Protocol):
    """Subset of ContextService needed for readiness."""

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        """Return RAG health including persisted index status.

        Returns:
            RAG dependency health snapshot.
        """


class ObsidianReadinessService(Protocol):
    """Subset of ObsidianService needed for readiness."""

    async def status(self) -> ObsidianVaultStatus:
        """Return vault/index status.

        Returns:
            Obsidian vault/index status snapshot.
        """


@runtime_checkable
class ObsidianDataIntegrityService(Protocol):
    """Managed-source boundary used by integrity diagnostics."""

    async def managed_markdown_paths(self) -> list[str]:
        """Return every managed Markdown path, including invalid notes.

        Returns:
            Vault-relative managed Markdown paths.
        """


class ReconciliationReadinessService(Protocol):
    """Subset of MemoryReconciliationReadinessService needed for readiness."""

    async def snapshot(self) -> MemoryReconciliationDiagnostics:
        """Return reconciliation diagnostics without mutating state.

        Returns:
            MemoryReconciliationDiagnostics: Operation result.
        """
