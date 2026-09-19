"""End-to-end Context change-log delta tests over the real API mutation paths."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from tests.memory.context_seed import seed_context

from app.main import app
from app.memory.domain.event_enum.context_enums import ContextKind
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_PREFIX = "obsidian:"
_RECORD_KINDS = {"created", "updated", "superseded", "archived", "deleted"}


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


def _canonical_payload(title: str, body: str, note_id: str) -> dict[str, object]:
    """Build an explicit canonical CONTEXT note-create payload.

    Args:
        title: Note title.
        body: Note body text.
        note_id: Deterministic note identifier.

    Returns:
        JSON payload for the obsidian create endpoint.
    """
    return {
        "title": title,
        "body": body,
        "alexandria_type": "context",
        "id": note_id,
        "match_by": "note_id",
        "status": "active",
        "project": "delta-flow",
        "frontmatter": {"scope": "project"},
    }


def test_canonical_and_sql_mutations_flow_into_delta_in_order() -> None:
    """create/update/supersede/archive through the API must order the log."""

    async def seed_sql_context() -> str:
        async with _database_session() as session:
            repository = SqlAlchemyContextRepository(session=session)
            seeded = await seed_context(
                session,
                kind=ContextKind.HANDOFF,
                title="SQL doomed handoff",
                content="# SQL doomed\n\nHard deleted through the API.",
            )
            await session.commit()
            return seeded.id

    sql_context_id = anyio.run(seed_sql_context)

    superseded_note_id = str(uuid4())
    replacement_note_id = str(uuid4())
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/obsidian/notes/create",
            json=_canonical_payload(
                "Delta canonical A", "# Canonical A\n\nFirst body.", superseded_note_id
            ),
        )
        assert created.status_code == 201, created.text

        updated = client.post(
            "/obsidian/notes",
            json={
                "title": "Delta canonical A",
                "body": "# Canonical A\n\nSecond body with new content.",
                "alexandria_type": "context",
                "id": superseded_note_id,
                "status": "active",
                "project": "delta-flow",
                "frontmatter": {"scope": "project"},
            },
        )
        assert updated.status_code == 201, updated.text

        replacement = client.post(
            "/obsidian/notes/create",
            json=_canonical_payload(
                "Delta canonical B",
                "# Canonical B\n\nReplacement body.",
                replacement_note_id,
            ),
        )
        assert replacement.status_code == 201, replacement.text

        superseded = client.post(
            f"/memory/contexts/{_OBSIDIAN_PREFIX}{superseded_note_id}/supersede",
            json={"replacement_context_id": f"{_OBSIDIAN_PREFIX}{replacement_note_id}"},
        )
        assert superseded.status_code == 200, superseded.text

        archived = client.post(
            f"/memory/contexts/{_OBSIDIAN_PREFIX}{replacement_note_id}/archive",
        )
        assert archived.status_code == 200, archived.text

        deleted = client.delete(f"/memory/contexts/{sql_context_id}")
        assert deleted.status_code in (200, 204), deleted.text

        page_before = client.get("/memory/contexts/retrieval/changes").json()
        page_again = client.get("/memory/contexts/retrieval/changes").json()

    entries = page_before["entries"]
    kinds_by_context: dict[str, list[str]] = {}
    for entry in entries:
        assert entry["change_kind"] in _RECORD_KINDS
        assert entry["content_hash"]
        kinds_by_context.setdefault(entry["context_id"], []).append(
            entry["change_kind"]
        )

    assert kinds_by_context[superseded_note_id] == [
        "created",
        "updated",
        "superseded",
    ]
    # The replacement's active->current lifecycle normalization during
    # supersede leaves the note body (and its content hash) unchanged, so it
    # honestly records no "updated" entry; its own transitions are the
    # "created" and later "archived" writes.
    assert kinds_by_context[replacement_note_id] == [
        "created",
        "archived",
    ]
    assert kinds_by_context[sql_context_id] == ["deleted"]

    sequences = [entry["sequence"] for entry in entries]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)

    repeated = [entry["sequence"] for entry in page_again["entries"]]
    assert repeated == sequences


def test_delta_cursor_never_advances_past_undelivered_changes() -> None:
    """A cursor from a committed read must deliver only later mutations."""

    async def seed_one() -> str:
        async with _database_session() as session:
            repository = SqlAlchemyContextRepository(session=session)
            seeded = await seed_context(
                session,
                kind=ContextKind.HANDOFF,
                title="Cursor seed handoff",
                content="# Cursor seed\n\nArchived before the cursor read.",
            )
            await session.commit()
            await repository.archive(seeded.id)
            await session.commit()
            return seeded.id

    first_id = anyio.run(seed_one)

    with TestClient(app, raise_server_exceptions=False) as client:
        first_page = client.get("/memory/contexts/retrieval/changes").json()
        cursor = first_page["next_cursor"]
        assert [entry["context_id"] for entry in first_page["entries"]] == [first_id]

        async def archive_one_more() -> str:
            async with _database_session() as session:
                repository = SqlAlchemyContextRepository(session=session)
                seeded = await seed_context(
                    session,
                    kind=ContextKind.HANDOFF,
                    title="Cursor second handoff",
                    content="# Cursor second\n\nArchived after the cursor read.",
                )
                await session.commit()
                await repository.archive(seeded.id)
                await session.commit()
                return seeded.id

        second_id = anyio.run(archive_one_more)
        second_page = client.get(
            "/memory/contexts/retrieval/changes",
            params={"cursor_token": cursor},
        ).json()

    assert [entry["context_id"] for entry in second_page["entries"]] == [second_id]
    assert second_page["entries"][0]["sequence"] > first_page["entries"][-1]["sequence"]
    assert second_page["has_more"] is False


def test_delta_reads_do_not_grow_the_change_log() -> None:
    """Repeated delta reads must leave the durable log row count unchanged."""

    async def seed_and_archive() -> None:
        async with _database_session() as session:
            repository = SqlAlchemyContextRepository(session=session)
            seeded = await seed_context(
                session,
                kind=ContextKind.HANDOFF,
                title="Read-only delta handoff",
                content="# Read only\n\nArchived once.",
            )
            await session.commit()
            await repository.archive(seeded.id)
            await session.commit()

    anyio.run(seed_and_archive)

    with TestClient(app, raise_server_exceptions=False) as client:
        counts = []
        for _ in range(3):
            page = client.get("/memory/contexts/retrieval/changes").json()
            counts.append(len(page["entries"]))
            brief = client.post(
                "/memory/contexts/retrieval/brief",
                json={"query": "read only", "limit": 5},
            )
            assert brief.status_code == 200, brief.text
        after_briefs = client.get("/memory/contexts/retrieval/changes").json()

    assert len(set(counts)) == 1
    assert len(after_briefs["entries"]) == counts[0]
