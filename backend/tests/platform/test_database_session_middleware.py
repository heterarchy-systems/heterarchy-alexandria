"""Request-scoped database session middleware contracts."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.platform.middleware.database_session import (
    install_database_session_middleware,
    mark_database_transaction_independent,
    mark_database_transaction_read_only,
)
from app.shared.infrastructure.database import Database


def test_request_session_returns_connection_to_pool_when_route_uses_unclosed_session() -> (
    None
):
    """Route-created sessions should be closed by the request lifecycle."""
    database = Database(database_url=os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await database.initialize()
        try:
            yield
        finally:
            await database.shutdown()

    app = FastAPI(lifespan=lifespan)

    async def resolve_database() -> Database:
        return database

    install_database_session_middleware(app, resolve_database=resolve_database)

    @app.get("/uses-db")
    async def uses_db() -> dict[str, bool]:
        session = database.session()
        await session.execute(text("SELECT 1"))
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/uses-db")

        assert response.json() == {"ok": True}
        assert cast(QueuePool, database.engine.sync_engine.pool).checkedout() == 0


def test_request_session_commits_successful_route_changes() -> None:
    """Successful responses should commit work made through the request session."""
    database = Database(database_url=os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await database.initialize()
        async with database.engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE IF NOT EXISTS messages (value TEXT)")
            )
        try:
            yield
        finally:
            await database.shutdown()

    app = FastAPI(lifespan=lifespan)

    async def resolve_database() -> Database:
        return database

    install_database_session_middleware(app, resolve_database=resolve_database)

    @app.post("/messages")
    async def create_message() -> dict[str, bool]:
        session = database.session()
        await session.execute(text("INSERT INTO messages (value) VALUES ('saved')"))
        return {"ok": True}

    @app.get("/message-count")
    async def message_count() -> dict[str, int]:
        session = database.session()
        count = await session.scalar(text("SELECT COUNT(*) FROM messages"))
        return {"count": int(count or 0)}

    with TestClient(app) as client:
        response = client.post("/messages")
        count_response = client.get("/message-count")

        assert response.json() == {"ok": True}
        assert count_response.json() == {"count": 1}


def test_request_session_rolls_back_failed_route_changes() -> None:
    """Error responses should roll back work made through the request session."""
    database = Database(database_url=os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await database.initialize()
        async with database.engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE IF NOT EXISTS messages (value TEXT)")
            )
        try:
            yield
        finally:
            await database.shutdown()

    app = FastAPI(lifespan=lifespan)

    async def resolve_database() -> Database:
        return database

    install_database_session_middleware(app, resolve_database=resolve_database)

    @app.post("/messages")
    async def create_message() -> dict[str, bool]:
        session = database.session()
        await session.execute(text("INSERT INTO messages (value) VALUES ('lost')"))
        raise HTTPException(status_code=400, detail="bad message")

    @app.get("/message-count")
    async def message_count() -> dict[str, int]:
        session = database.session()
        count = await session.scalar(text("SELECT COUNT(*) FROM messages"))
        return {"count": int(count or 0)}

    with TestClient(app) as client:
        response = client.post("/messages")
        count_response = client.get("/message-count")

        assert response.json() == {"detail": "bad message"}
        assert count_response.json() == {"count": 0}


def test_independent_transaction_request_skips_middleware_commit() -> None:
    """Recovery-style handlers should own commit boundaries after DB replacement."""
    database = Database(database_url=os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await database.initialize()
        async with database.engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE IF NOT EXISTS messages (value TEXT)")
            )
        try:
            yield
        finally:
            await database.shutdown()

    app = FastAPI(lifespan=lifespan)

    async def resolve_database() -> Database:
        return database

    install_database_session_middleware(app, resolve_database=resolve_database)

    @app.post("/independent")
    async def independent(request: Request) -> dict[str, bool]:
        mark_database_transaction_independent(request)
        session = database.session()
        await session.execute(text("INSERT INTO messages (value) VALUES ('owned')"))
        return {"ok": True}

    @app.get("/message-count")
    async def message_count() -> dict[str, int]:
        session = database.session()
        count = await session.scalar(text("SELECT COUNT(*) FROM messages"))
        return {"count": int(count or 0)}

    with TestClient(app) as client:
        response = client.post("/independent")
        count_response = client.get("/message-count")

        assert response.json() == {"ok": True}
        assert count_response.json() == {"count": 0}


def test_source_read_response_survives_failed_metadata_transaction() -> None:
    """Source-only success rolls back failed projection SQL instead of committing it."""
    database = Database(database_url=os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await database.initialize()
        try:
            yield
        finally:
            await database.shutdown()

    app = FastAPI(lifespan=lifespan)

    async def resolve_database() -> Database:
        return database

    install_database_session_middleware(app, resolve_database=resolve_database)

    @app.get("/source")
    async def source(request: Request) -> dict[str, str]:
        mark_database_transaction_read_only(request)
        try:
            await database.session().execute(text("SELECT 1 / 0"))
        except SQLAlchemyError:
            return {"body": "durable source", "index_status": "unavailable"}
        raise AssertionError("the metadata query must fail")

    with TestClient(app) as client:
        response = client.get("/source")
        assert response.status_code == 200
        assert response.json() == {
            "body": "durable source",
            "index_status": "unavailable",
        }
        assert cast(QueuePool, database.engine.sync_engine.pool).checkedout() == 0
