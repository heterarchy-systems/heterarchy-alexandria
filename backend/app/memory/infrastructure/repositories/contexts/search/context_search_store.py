"""SQL-backed Context FTS and vector search store."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.infrastructure.repositories.contexts.embeddings.vector_search import (
    search_context_vectors,
)
from app.memory.infrastructure.repositories.contexts.search.fts_search import (
    search_context_fts,
)


class ContextSearchStore:
    """Own SQL FTS and vector recall over Context chunks."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the Context search store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def search_fts(
        self,
        recall: ContextFtsRecall,
    ) -> list[ContextSearchMatch]:
        """Search Context chunks with PostgreSQL full-text search.

        Args:
            recall: Structured FTS recall contract.

        Returns:
            Ranked Context matches.
        """
        return await search_context_fts(self._session, recall)

    async def search_vector(
        self,
        recall: ContextVectorRecall,
    ) -> list[ContextSearchMatch]:
        """Search Context chunks by vector similarity.

        Args:
            recall: Structured vector recall contract.

        Returns:
            Ranked Context matches.
        """
        return await search_context_vectors(self._session, recall)
