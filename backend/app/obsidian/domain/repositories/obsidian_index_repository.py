"""Composite contract for transactional Obsidian index operations."""

from __future__ import annotations

from app.obsidian.domain.repositories.obsidian_index_error_repository import (
    IObsidianIndexErrorRepository,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.domain.repositories.obsidian_index_write_repository import (
    IObsidianIndexWriteRepository,
)


class IObsidianIndexRepository(
    IObsidianIndexWriteRepository,
    IObsidianIndexQueryRepository,
    IObsidianIndexErrorRepository,
):
    """Combine focused Obsidian index ports for transaction-scoped services."""
