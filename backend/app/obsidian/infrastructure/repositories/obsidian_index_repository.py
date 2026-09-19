"""Stable SQLAlchemy repository facade for the Obsidian index cache."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.repositories.obsidian_index_error_store import (
    ObsidianIndexErrorStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_query_store import (
    ObsidianIndexQueryStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository_delegates import (
    ObsidianIndexErrorRepositoryDelegate,
    ObsidianIndexQueryRepositoryDelegate,
    ObsidianIndexWriteRepositoryDelegate,
)
from app.obsidian.infrastructure.repositories.obsidian_index_write_store import (
    ObsidianIndexChangeRecorder,
    ObsidianIndexWriteStore,
)


class SqlAlchemyObsidianIndexRepository(
    ObsidianIndexWriteRepositoryDelegate,
    ObsidianIndexQueryRepositoryDelegate,
    ObsidianIndexErrorRepositoryDelegate,
    IObsidianIndexRepository,
):
    """Assemble focused Obsidian index stores behind the stable repository API."""

    def __init__(
        self,
        session: AsyncSession,
        context_change_recorder: ObsidianIndexChangeRecorder | None = None,
    ) -> None:
        """Create the repository facade.

        Args:
            session: Active async database session.
            context_change_recorder: Optional canonical Context change
                observer appended inside each index-write transaction.
        """
        self._session = session
        self._write_store = ObsidianIndexWriteStore(
            session,
            context_change_recorder=context_change_recorder,
        )
        self._query_store = ObsidianIndexQueryStore(session)
        self._error_store = ObsidianIndexErrorStore(session)
