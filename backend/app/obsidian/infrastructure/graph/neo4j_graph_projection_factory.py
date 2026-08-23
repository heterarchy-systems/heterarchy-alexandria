"""Lifecycle factory for the optional Neo4j graph projection adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from neo4j import AsyncGraphDatabase

from app.obsidian.infrastructure.graph.neo4j_graph_projection_contracts import (
    Neo4jProjectionDriver,
)
from app.obsidian.infrastructure.graph.neo4j_obsidian_graph_projection_repository import (
    Neo4jObsidianGraphProjectionRepository,
)
from app.platform.config.app_config import AppConfig


@asynccontextmanager
async def optional_neo4j_graph_projection_repository(
    config: AppConfig,
) -> AsyncIterator[Neo4jObsidianGraphProjectionRepository | None]:
    """Yield an adapter only for explicit Neo4j configuration.

    The official Neo4j Python driver is an application dependency. Disabled mode
    still returns before creating a driver or opening any connection/session.

    Args:
        config: Typed application configuration.

    Yields:
        One application-lifetime adapter, or ``None`` while disabled.
    """
    if config.graph_read_model == "disabled":
        yield None
        return

    # Cast justified: the official Neo4j driver exposes a wider AsyncSession
    # signature than this adapter consumes; the repository uses only the narrow
    # driver/session methods covered by integration and fake-driver tests.
    driver = cast(
        Neo4jProjectionDriver,
        AsyncGraphDatabase.driver(
            config.neo4j_uri or "",
            auth=(config.neo4j_username or "", config.neo4j_password_value()),
        ),
    )
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=driver,
        database=config.neo4j_database,
    )
    try:
        yield repository
    finally:
        await repository.close()
