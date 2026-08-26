"""PostgreSQL contracts for the cheap Obsidian projection source revision."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import anyio

from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianFileORM
from app.obsidian.infrastructure.repositories.obsidian_index_query_store import (
    ObsidianIndexQueryStore,
)
from app.shared.infrastructure.database import Database


def _database_url() -> str:
    """Return the isolated PostgreSQL test URL.

    Returns:
        PostgreSQL URL supplied by the canonical test harness.
    """
    return os.environ["DATABASE_URL"]


def _indexed_file(indexed_at: datetime) -> ObsidianFileORM:
    """Build one complete indexed-note row for revision tests.

    Args:
        indexed_at: Derived index revision timestamp.

    Returns:
        Complete Obsidian file ORM row in indexed state.
    """
    return ObsidianFileORM(
        note_id="projection-revision-note",
        relative_path="Alexandria/Contexts/Projection Revision.md",
        alexandria_type="context",
        title="Projection Revision",
        status="active",
        tags=[],
        project="heterarchy-alexandria",
        source="test",
        content_hash="a" * 64,
        frontmatter_json={"scope": "GLOBAL"},
        body="# Projection Revision\n\nInitial body.",
        index_status=ObsidianIndexStatus.INDEXED.value,
        error_message=None,
        size_bytes=35,
        modified_at=indexed_at,
        indexed_at=indexed_at,
    )


def test_projection_source_revision_detects_update_and_delete() -> None:
    """The cheap token must change on indexed updates and return to empty after delete."""

    async def scenario() -> tuple[str, str, str, str]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        store = ObsidianIndexQueryStore(session)
        try:
            empty_revision = await store.projection_source_revision()
            indexed_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
            model = _indexed_file(indexed_at)
            session.add(model)
            await session.flush()
            created_revision = await store.projection_source_revision()

            model.body = "# Projection Revision\n\nUpdated body."
            model.content_hash = "b" * 64
            model.indexed_at = indexed_at + timedelta(microseconds=1)
            await session.flush()
            updated_revision = await store.projection_source_revision()

            await session.delete(model)
            await session.flush()
            deleted_revision = await store.projection_source_revision()
        finally:
            await session.close()
            await database.shutdown()
        return empty_revision, created_revision, updated_revision, deleted_revision

    empty_revision, created_revision, updated_revision, deleted_revision = anyio.run(
        scenario
    )

    assert empty_revision == "obsidian-index:0:none"
    assert created_revision.startswith("obsidian-index:1:")
    assert updated_revision.startswith("obsidian-index:1:")
    assert updated_revision != created_revision
    assert deleted_revision == empty_revision
