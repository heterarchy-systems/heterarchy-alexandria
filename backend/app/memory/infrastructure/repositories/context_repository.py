"""Stable SQLAlchemy repository facade for Context storage and retrieval."""

from __future__ import annotations

from app.memory.domain.repositories.contexts.context_repository import (
    IContextRepository,
)
from app.memory.infrastructure.repositories.contexts.embeddings.context_embedding_store import (
    ContextEmbeddingStore,
)
from app.memory.infrastructure.repositories.contexts.records.context_record_mutation_store import (
    ContextRecordMutationStore,
)
from app.memory.infrastructure.repositories.contexts.records.context_record_query_store import (
    ContextRecordQueryStore,
)
from app.memory.infrastructure.repositories.contexts.records.context_repository_delegates import (
    ContextEmbeddingRepositoryDelegate,
    ContextRecordMutationRepositoryDelegate,
    ContextRecordQueryRepositoryDelegate,
    ContextSearchRepositoryDelegate,
)
from app.memory.infrastructure.repositories.contexts.search.context_search_store import (
    ContextSearchStore,
)
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyContextRepository(
    ContextRecordQueryRepositoryDelegate,
    ContextRecordMutationRepositoryDelegate,
    ContextSearchRepositoryDelegate,
    ContextEmbeddingRepositoryDelegate,
    IContextRepository,
):
    """Assemble focused Context stores behind the stable repository API."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the repository facade.

        Args:
            session: Active async database session.
        """
        self._query_store = ContextRecordQueryStore(session)
        self._mutation_store = ContextRecordMutationStore(session)
        self._search_store = ContextSearchStore(session)
        self._embedding_store = ContextEmbeddingStore(session)
