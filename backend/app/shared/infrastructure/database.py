"""Shared PostgreSQL asynchronous database bootstrap and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from app.shared.infrastructure.database_session_scope import DatabaseSessionScope
from app.shared.infrastructure.postgres_database_policy import (
    POSTGRES_MAX_OVERFLOW,
    POSTGRES_POOL_RECYCLE_SECONDS,
    POSTGRES_POOL_SIZE,
    POSTGRES_POOL_TIMEOUT_SECONDS,
    postgres_connect_args,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

__all__ = (
    "Base",
    "Database",
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base used by backend ORM models."""


class Database:
    """Coordinate the PostgreSQL engine and request-scoped async sessions."""

    def __init__(
        self,
        *,
        database_url: str,
        create_schema: bool = False,
    ) -> None:
        """Create a PostgreSQL database coordinator.

        Args:
            database_url: PostgreSQL async SQLAlchemy URL.
            create_schema: Create ORM tables directly for isolated tests.

        Raises:
            ValueError: If a non-PostgreSQL database URL is supplied.
        """
        self._database_url = database_url
        self._create_schema = create_schema
        self._dialect_name = make_url(database_url).get_backend_name()
        if self._dialect_name != "postgresql":
            raise ValueError("heterarchy-alexandria runtime supports PostgreSQL only")
        if create_schema:
            # Test-only coordinators must not retain asyncpg connections across
            # independent event loops used by sync TestClient/anyio boundaries.
            self.engine = create_async_engine(
                database_url,
                echo=False,
                future=True,
                pool_pre_ping=True,
                connect_args=postgres_connect_args(),
                poolclass=NullPool,
            )
        else:
            self.engine = create_async_engine(
                database_url,
                echo=False,
                future=True,
                pool_pre_ping=True,
                connect_args=postgres_connect_args(),
                pool_size=POSTGRES_POOL_SIZE,
                max_overflow=POSTGRES_MAX_OVERFLOW,
                pool_timeout=POSTGRES_POOL_TIMEOUT_SECONDS,
                pool_recycle=POSTGRES_POOL_RECYCLE_SECONDS,
            )
        self._session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        self._session_scope = DatabaseSessionScope(
            owner_identity=id(self),
            session_factory=self._session_factory,
        )

    async def initialize(self) -> None:
        """Initialize the database connection lifecycle.

        Runtime schema creation remains Alembic-owned. Direct metadata creation is
        available only through the explicit test-only option.
        """
        async with self.engine.begin() as connection:
            if not self._create_schema:
                await connection.execute(text("SELECT 1"))
                return
            await connection.run_sync(Base.metadata.create_all)

    async def shutdown(self) -> None:
        """Release SQLAlchemy resources."""
        await self.engine.dispose()

    async def ping(self) -> bool:
        """Check whether the async database connection is available.

        Returns:
            Whether a trivial query succeeded.
        """
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    @property
    def dialect_name(self) -> str:
        """Return the normalized SQLAlchemy backend name.

        Returns:
            PostgreSQL backend name.
        """
        return self._dialect_name

    @property
    def is_postgresql(self) -> bool:
        """Return true for the only supported runtime backend.

        Returns:
            True because heterarchy-alexandria runtime persistence is PostgreSQL-only.
        """
        return True

    def session(self) -> AsyncSession:
        """Create or reuse a SQLAlchemy session.

        Returns:
            Request-bound session when present, otherwise a new session.
        """
        return self._session_scope.session()

    @asynccontextmanager
    async def request_session(self) -> AsyncIterator[AsyncSession]:
        """Bind one managed session to the current request context.

        Yields:
            Session shared by repositories created during one request.
        """
        async with self._session_scope.request_session() as session:
            yield session

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the configured async session factory.

        Returns:
            Configured async SQLAlchemy session maker.
        """
        return self._session_scope.session_factory()

    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Yield a managed session for FastAPI dependency injection.

        Yields:
            Managed async SQLAlchemy session.
        """
        async for session in self._session_scope.get_session():
            yield session
