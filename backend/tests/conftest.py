"""Shared backend test configuration."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.platform.config.database_config import DatabaseConfig
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

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

_TEST_ALEXANDRIA_ROOT.mkdir(parents=True, exist_ok=True)

# Environment variables take precedence over the private repository .env file.
# Set them before test modules import the global FastAPI application container.
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
os.environ["SERVICE_OBSIDIAN_VAULT_PATH"] = str(_TEST_VAULT_PATH)
os.environ["SERVICE_ALEXANDRIA_OBSIDIAN_ROOT"] = "Alexandria"
os.environ["SERVICE_GRAPH_READ_MODEL"] = "disabled"
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


async def _truncate_test_database() -> None:
    engine = create_async_engine(_TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
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
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_postgres_test_state() -> None:
    """Clear mutable PostgreSQL rows after every test while keeping migrations intact."""
    yield
    asyncio.run(_truncate_test_database())


def pytest_sessionstart(session: pytest.Session) -> None:
    """Create a migration-faithful isolated PostgreSQL database before collection."""
    del session
    asyncio.run(_create_test_database())
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: pytest.ExitCode,
) -> None:
    """Drop only the session-owned PostgreSQL database and temporary Vault."""
    del session, exitstatus
    try:
        asyncio.run(_drop_test_database())
    finally:
        shutil.rmtree(_TEST_RUNTIME_ROOT, ignore_errors=True)
