"""SQLAlchemy transaction boundary for resumable embedding batches."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyContextEmbeddingBatchTransaction:
    """Keep CPU inference outside transactions and commit each durable batch."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the transaction boundary to one request-local session.

        Args:
            session: Async SQLAlchemy session shared by embedding search sources.
        """
        self._session = session

    async def release_read_transaction(self) -> None:
        """Rollback the read-only selection transaction before CPU inference."""
        if self._session.in_transaction():
            await self._session.rollback()

    async def commit_embedding_updates(self) -> None:
        """Commit one embedding batch so later batches remain independently durable."""
        if self._session.in_transaction():
            await self._session.commit()
