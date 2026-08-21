"""Composite port for Context storage, retrieval, and search operations."""

from __future__ import annotations

from app.memory.domain.repositories.contexts.context_record_mutation_repository import (
    IContextRecordMutationRepository,
)
from app.memory.domain.repositories.contexts.context_record_query_repository import (
    IContextRecordQueryRepository,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)


class IContextRepository(
    IContextRecordQueryRepository,
    IContextRecordMutationRepository,
    IContextSearchSource,
):
    """Combine focused Context persistence ports for transaction-scoped services."""
