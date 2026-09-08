"""Alembic environment for heterarchy-alexandria backend migrations."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.mcp_server.local_oauth.orm as _mcp_local_oauth_models  # noqa: F401
import app.memory.infrastructure.models.context_models as _context_models  # noqa: F401
import app.memory.infrastructure.models.reconciliation_models as _reconciliation_models  # noqa: F401
import app.obsidian.infrastructure.models.obsidian_index_models as _obsidian_index_models  # noqa: F401
from app.platform.config.database_config import DatabaseConfig
from app.shared.infrastructure.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", DatabaseConfig().url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without opening a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations on an existing sync connection."""
    if connection.dialect.name == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alembic_version (
                    version_num VARCHAR(255) NOT NULL PRIMARY KEY
                )
                """
            )
        )
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through its sync bridge."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
