"""PostgreSQL database lifecycle contracts."""

from __future__ import annotations

import os

import anyio
import pytest
from app.shared.infrastructure import postgres_database_policy
from app.shared.infrastructure.database import Database
from sqlalchemy import text


def test_database_rejects_non_postgresql_urls() -> None:
    """Runtime persistence must not accept SQLite compatibility URLs."""
    with pytest.raises(ValueError, match="PostgreSQL only"):
        Database(database_url="sqlite+aiosqlite:///:memory:")


def test_database_initialize_and_ping_postgresql() -> None:
    """Runtime startup should validate the migration-managed PostgreSQL database."""

    async def scenario() -> tuple[bool, int]:
        database = Database(database_url=os.environ["DATABASE_URL"])
        await database.initialize()
        try:
            async with database.session_factory()() as session:
                scalar = await session.scalar(text("SELECT 1"))
            return await database.ping(), int(scalar or 0)
        finally:
            await database.shutdown()

    healthy, scalar = anyio.run(scenario)
    assert healthy is True
    assert scalar == 1


def test_database_request_session_reuses_request_bound_session() -> None:
    """Repositories created in one request should share the same SQLAlchemy session."""

    async def scenario() -> bool:
        database = Database(database_url=os.environ["DATABASE_URL"])
        await database.initialize()
        try:
            async with database.request_session() as request_session:
                return database.session() is request_session
        finally:
            await database.shutdown()

    assert anyio.run(scenario) is True


def test_postgres_database_uses_bounded_pool_and_dialect_flags() -> None:
    """PostgreSQL engines should expose bounded pooling without opening a connection."""
    database = Database(database_url=os.environ["DATABASE_URL"])
    try:
        pool = database.engine.pool
        assert database.dialect_name == "postgresql"
        assert database.is_postgresql is True
        assert pool.size() == postgres_database_policy.POSTGRES_POOL_SIZE
        assert pool._max_overflow == postgres_database_policy.POSTGRES_MAX_OVERFLOW
        assert pool._timeout == postgres_database_policy.POSTGRES_POOL_TIMEOUT_SECONDS
    finally:
        anyio.run(database.shutdown)


def test_postgres_connect_args_bound_commands_locks_and_idle_transactions() -> None:
    """PostgreSQL driver policy should bound stalled work at multiple layers."""
    connect_args = postgres_database_policy.postgres_connect_args()
    server_settings = connect_args["server_settings"]

    assert connect_args["command_timeout"] == 30.0
    assert isinstance(server_settings, dict)
    assert server_settings == {
        "application_name": "heterarchy-alexandria",
        "timezone": "UTC",
        "statement_timeout": "30000",
        "lock_timeout": "5000",
        "idle_in_transaction_session_timeout": "60000",
    }
