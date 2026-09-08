"""Shared backend test configuration."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.platform.config.database_config import DatabaseConfig

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="heterarchy-alexandria-tests-"))
_TEST_VAULT_PATH = _TEST_RUNTIME_ROOT / "vault"
_TEST_ALEXANDRIA_ROOT = _TEST_VAULT_PATH / "Alexandria"
_TEST_DATABASE_NAME = f"alexandria_test_{uuid4().hex[:16]}"
_SOURCE_DATABASE_URL = DatabaseConfig().url
_SOURCE_URL = make_url(_SOURCE_DATABASE_URL)
if _SOURCE_URL.get_backend_name() != "postgresql":
    raise RuntimeError("Backend tests require a PostgreSQL DATABASE_URL")
_TEST_DATABASE_URL = (
    _SOURCE_DATABASE_URL.rsplit("/", maxsplit=1)[0] + f"/{_TEST_DATABASE_NAME}"
)
_ADMIN_DATABASE_URL = _SOURCE_DATABASE_URL.rsplit("/", maxsplit=1)[0] + "/postgres"
_collection_started_at: float | None = None
_test_cleanup_count = 0
_test_cleanup_total_elapsed = 0.0
_test_cleanup_max_elapsed = 0.0

_TEST_ALEXANDRIA_ROOT.mkdir(parents=True, exist_ok=True)

# Environment variables take precedence over the private repository .env file.
# Set them before test modules import the global FastAPI application container.
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
os.environ["SERVICE_OBSIDIAN_VAULT_PATH"] = str(_TEST_VAULT_PATH)
os.environ["SERVICE_ALEXANDRIA_OBSIDIAN_ROOT"] = "Alexandria"
os.environ["SERVICE_GRAPH_READ_MODEL"] = "postgresql"
os.environ["SERVICE_REDIS_URL"] = ""
os.environ["SERVICE_RAG_EMBEDDING_RECOVERY_ON_STARTUP"] = "false"
os.environ["SERVICE_RAG_EMBEDDING_RECOVERY_ON_VAULT_REINDEX"] = "false"


async def _create_test_database() -> None:
    engine = create_async_engine(_ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{_TEST_DATABASE_NAME}"'))
    finally:
        await engine.dispose()


async def _drop_test_database() -> None:
    engine = create_async_engine(_ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": _TEST_DATABASE_NAME},
            )
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{_TEST_DATABASE_NAME}"')
            )
    finally:
        await engine.dispose()


async def _truncate_test_database(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = [str(row[0]) for row in rows]
        if tables:
            quoted = ", ".join(f'"{table}"' for table in tables)
            await connection.execute(
                text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
            )


@pytest.fixture(scope="session")
def _postgres_cleanup_runtime() -> Iterator[tuple[asyncio.Runner, AsyncEngine]]:
    """Own one cleanup-only loop and connection, separate from application loops."""
    with asyncio.Runner() as runner:
        engine = create_async_engine(
            _TEST_DATABASE_URL,
            isolation_level="AUTOCOMMIT",
            pool_size=1,
            max_overflow=0,
        )
        try:
            yield runner, engine
        finally:
            runner.run(engine.dispose())


@pytest.fixture(autouse=True)
def _isolate_postgres_test_state(
    _postgres_cleanup_runtime: tuple[asyncio.Runner, AsyncEngine],
) -> Iterator[None]:
    """Clear mutable PostgreSQL rows after every test while keeping migrations intact."""
    global _test_cleanup_count, _test_cleanup_total_elapsed, _test_cleanup_max_elapsed
    yield
    cleanup_started = time.monotonic()
    try:
        runner, engine = _postgres_cleanup_runtime
        runner.run(_truncate_test_database(engine))
    finally:
        cleanup_elapsed = time.monotonic() - cleanup_started
        _test_cleanup_count += 1
        _test_cleanup_total_elapsed += cleanup_elapsed
        _test_cleanup_max_elapsed = max(_test_cleanup_max_elapsed, cleanup_elapsed)


@pytest.fixture(autouse=True)
def _override_retrieval_kernel_for_host_tests() -> None:
    """Use the deterministic tests-only retrieval provider outside native E2E gates."""
    from dependency_injector import providers
    from tests.memory.context_retrieval_kernel_test_provider import (
        create_test_context_retrieval_kernel_provider,
    )

    from app.main import app

    provider = app.state.container.memory.retrieval_kernel_provider
    with provider.override(
        providers.Object(create_test_context_retrieval_kernel_provider())
    ):
        yield


@pytest.fixture
def restore_default_app_wiring() -> Iterator[None]:
    """Release alternate test-app DI bindings before the next request uses the default app."""
    try:
        yield
    finally:
        from app.main import app

        app.state.container.wire()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Create a migration-faithful isolated PostgreSQL database before collection."""
    del session
    database_started = time.monotonic()
    print("[pytest-setup] Creating isolated PostgreSQL test database...", flush=True)
    asyncio.run(_create_test_database())
    database_elapsed = time.monotonic() - database_started
    print(
        f"[pytest-setup] Test database created in {database_elapsed:.1f}s.",
        flush=True,
    )

    migration_started = time.monotonic()
    print("[pytest-setup] Applying Alembic migrations to head...", flush=True)
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    migration_elapsed = time.monotonic() - migration_started
    print(
        f"[pytest-setup] Alembic migrations completed in {migration_elapsed:.1f}s.",
        flush=True,
    )


def pytest_collection(session: pytest.Session) -> None:
    """Report when test collection begins after database bootstrap."""
    global _collection_started_at
    del session
    _collection_started_at = time.monotonic()
    print("[pytest-setup] Collecting tests...", flush=True)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Report the collected test count and elapsed collection time."""
    collection_elapsed = (
        0.0
        if _collection_started_at is None
        else time.monotonic() - _collection_started_at
    )
    if session.config.option.collectonly:
        outcome = "; collection-only run, no tests will execute."
    else:
        outcome = "; running tests now."
    print(
        f"[pytest-setup] Collected {len(session.items)} tests in "
        f"{collection_elapsed:.2f}s{outcome}",
        flush=True,
    )


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: pytest.ExitCode,
) -> None:
    """Drop only the session-owned PostgreSQL database and temporary Vault."""
    del session, exitstatus
    if _test_cleanup_count:
        cleanup_average = _test_cleanup_total_elapsed / _test_cleanup_count
        print(
            f"[pytest-setup] Per-test PostgreSQL cleanup: {_test_cleanup_count} "
            f"truncations in {_test_cleanup_total_elapsed:.2f}s "
            f"(average {cleanup_average:.3f}s, max {_test_cleanup_max_elapsed:.3f}s).",
            flush=True,
        )
    else:
        print(
            "[pytest-setup] Per-test PostgreSQL cleanup: no truncations recorded.",
            flush=True,
        )
    print("[pytest-setup] Dropping isolated PostgreSQL test database...", flush=True)
    try:
        asyncio.run(_drop_test_database())
    finally:
        shutil.rmtree(_TEST_RUNTIME_ROOT, ignore_errors=True)
    print("[pytest-setup] PostgreSQL test database cleanup complete.", flush=True)
