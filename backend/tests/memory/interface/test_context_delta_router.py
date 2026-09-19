"""Router contract tests for the Context change-log delta endpoints."""

from __future__ import annotations

import os
from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from json import dumps
from pathlib import Path

import anyio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.memory.context_seed import seed_context

from app.main import app
from app.memory.domain.event_enum.context_enums import ContextKind
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.shared.infrastructure.database import Database


@asynccontextmanager
async def _database_session() -> AsyncIterator[AsyncSession]:
    """Yield one PostgreSQL session fully contained in one event loop."""
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        async with database.session() as session:
            yield session
    finally:
        await database.shutdown()


async def _seed_and_archive(session: AsyncSession, title: str) -> str:
    """Seed one context and archive it through the hooked mutation site.

    Args:
        session: Active async database session.
        title: Seeded context title.

    Returns:
        Archived context identifier.
    """
    repository = SqlAlchemyContextRepository(session=session)
    seeded = await seed_context(
        session,
        kind=ContextKind.HANDOFF,
        title=title,
        content=f"# {title}\n\nArchived for the delta route.",
    )
    await session.commit()
    await repository.archive(seeded.id)
    await session.commit()
    return seeded.id


def _foreign_scope_token() -> str:
    """Encode a structurally valid cursor token bound to a foreign scope.

    Returns:
        Encoded opaque token with a foreign scope string.
    """
    payload = dumps({"v": 1, "scope": "other-consumer", "last_sequence": 0})
    return urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def test_context_changes_route_returns_entries_after_archive(tmp_path: Path) -> None:
    """The delta route should expose change entries with bounded pagination."""

    async def seed_and_archive() -> str:
        async with _database_session() as session:
            return await _seed_and_archive(session, "Delta route handoff")

    async def archive_one_more() -> None:
        async with _database_session() as session:
            await _seed_and_archive(session, "Delta route second")

    context_id = anyio.run(seed_and_archive)
    with TestClient(app, raise_server_exceptions=False) as client:
        initial = client.get("/memory/contexts/retrieval/changes")
        paged = client.get("/memory/contexts/retrieval/changes", params={"max_rows": 1})
        body_page = client.post(
            "/memory/contexts/retrieval/changes", json={"max_rows": 2}
        )
        _ = anyio.run(archive_one_more)
        after_second = client.get("/memory/contexts/retrieval/changes")

    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload["has_more"] is False
    assert initial_payload["next_cursor"]

    assert paged.status_code == 200
    paged_payload = paged.json()
    assert len(paged_payload["entries"]) == 1
    assert paged_payload["entries"][0]["context_id"] == context_id
    assert paged_payload["entries"][0]["change_kind"] == "archived"
    assert len(paged_payload["entries"][0]["content_hash"]) == 64
    assert paged_payload["entries"][0]["sequence"] >= 1

    assert body_page.status_code == 200

    assert after_second.status_code == 200
    after_payload = after_second.json()
    assert [entry["change_kind"] for entry in after_payload["entries"]] == [
        "archived",
        "archived",
    ]


def test_context_changes_route_maps_cursor_errors_typed(tmp_path: Path) -> None:
    """Corrupt cursors map to 400 and foreign-scope cursors map to 409."""
    del tmp_path

    with TestClient(app, raise_server_exceptions=False) as client:
        corrupt = client.get(
            "/memory/contexts/retrieval/changes", params={"cursor_token": "@@@"}
        )
        foreign = client.get(
            "/memory/contexts/retrieval/changes",
            params={"cursor_token": _foreign_scope_token()},
        )
        body_corrupt = client.post(
            "/memory/contexts/retrieval/changes", json={"cursor_token": "@@@"}
        )

    assert corrupt.status_code == 400
    assert foreign.status_code == 409
    assert body_corrupt.status_code == 400
