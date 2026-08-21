"""Request-scoped asynchronous SQLAlchemy session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_current_request_sessions: ContextVar[dict[int, AsyncSession] | None] = ContextVar(
    "current_request_sessions",
    default=None,
)


class DatabaseSessionScope:
    """Bind one async session factory to process and request-local scopes."""

    def __init__(
        self,
        owner_identity: int,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Initialize session scope state.

        Args:
            owner_identity: Stable identity for one Database coordinator.
            session_factory: Configured async SQLAlchemy session factory.
        """
        self._owner_identity = owner_identity
        self._session_factory = session_factory

    def session(self) -> AsyncSession:
        """Return the request-bound session or create an unmanaged session.

        Returns:
            Active request session when bound, otherwise a new session.
        """
        current_sessions = _current_request_sessions.get()
        if (
            current_sessions is not None
            and (current_session := current_sessions.get(self._owner_identity))
            is not None
        ):
            return current_session
        return self._session_factory()

    @asynccontextmanager
    async def request_session(self) -> AsyncIterator[AsyncSession]:
        """Bind one managed session to the current request context.

        Yields:
            Session shared by repositories created during one request.
        """
        async with self._session_factory() as session:
            current_sessions = _current_request_sessions.get()
            next_sessions = {} if current_sessions is None else current_sessions.copy()
            next_sessions[self._owner_identity] = session
            token = _current_request_sessions.set(next_sessions)
            try:
                yield session
            finally:
                _current_request_sessions.reset(token)

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the configured async session factory.

        Returns:
            Configured session maker.
        """
        return self._session_factory

    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Yield a managed session for FastAPI dependency injection.

        Yields:
            Managed async SQLAlchemy session.
        """
        async with self._session_factory() as session:
            yield session
