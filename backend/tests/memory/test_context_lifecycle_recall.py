"""Lifecycle recall contract tests for Context and Obsidian sources."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import anyio
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
    ContextScope,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_context_mapping import (
    is_recall_visible,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextSearchRequest,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianFileORM
from app.shared.infrastructure.database import Database
from app.shared.serialization.orjson_codec import dumps_json
from tests.memory.context_seed import seed_context


@asynccontextmanager
async def _temporary_database(path: Path) -> AsyncIterator[Database]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        yield database
    finally:
        await database.shutdown()


def test_explicit_archived_recall_preserves_default_and_scope_safety(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[list[str], list[str], list[str]]:
        async with (
            _temporary_database(tmp_path / "lifecycle.db") as database,
            database.session() as session,
        ):
            service = ContextService(
                repository=SqlAlchemyContextRepository(session=session)
            )
            alpha = await seed_context(
                session,
                content="administrative archived recall alpha",
                project="alpha",
            )
            beta = await seed_context(
                session,
                content="administrative archived recall beta",
                project="beta",
            )
            await session.commit()
            await service.archive(alpha.id)
            await service.archive(beta.id)
            await session.commit()

            default_pack = await service.search(
                query="administrative archived recall",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
            )
            archived_pack = await service.search(
                query="administrative archived recall",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                include_lifecycle_statuses=[ContextRecallLifecycleStatus.ARCHIVED],
            )
            scoped_pack = await service.search(
                query="administrative archived recall",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                project="alpha",
                include_scopes=[ContextScope.PROJECT],
                include_lifecycle_statuses=[ContextRecallLifecycleStatus.ARCHIVED],
            )
            return (
                [match.context.id for match in default_pack.matches],
                [match.context.id for match in archived_pack.matches],
                [match.context.id for match in scoped_pack.matches],
            )

    default_ids, archived_ids, scoped_ids = anyio.run(scenario)

    assert default_ids == []
    assert archived_ids == []
    assert len(scoped_ids) == 1


def test_explicit_pending_review_recall_keeps_saved_default_compatibility(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[list[str], list[str], str, str]:
        async with (
            _temporary_database(tmp_path / "pending.db") as database,
            database.session() as session,
        ):
            service = ContextService(
                repository=SqlAlchemyContextRepository(session=session)
            )
            saved = await seed_context(
                session,
                content="lifecycle compatibility saved",
            )
            pending = await seed_context(
                session,
                content="lifecycle compatibility pending",
                status=ContextStorageStatus.PENDING_REVIEW,
            )
            await session.commit()
            default_pack = await service.search(
                query="lifecycle compatibility",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
            )
            pending_pack = await service.search(
                query="lifecycle compatibility",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                include_lifecycle_statuses=[
                    ContextRecallLifecycleStatus.PENDING_REVIEW
                ],
            )
            return (
                [match.context.id for match in default_pack.matches],
                [match.context.id for match in pending_pack.matches],
                saved.id,
                pending.id,
            )

    default_ids, pending_ids, saved_id, pending_id = anyio.run(scenario)

    assert default_ids == [saved_id]
    assert pending_ids == [pending_id]


def test_obsidian_administrative_statuses_remain_index_safe() -> None:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    note = ObsidianFileORM(
        note_id="note-1",
        relative_path="Memory/note-1.md",
        alexandria_type=AlexandriaNoteType.CONTEXT.value,
        title="Lifecycle note",
        status="superseded",
        tags=[],
        project="alpha",
        source="Hermes",
        content_hash="hash",
        frontmatter_json={},
        body="content",
        index_status=ObsidianIndexStatus.INDEXED.value,
        error_message=None,
        size_bytes=7,
        modified_at=now,
        indexed_at=now,
    )

    assert is_recall_visible(note, None) is False
    assert (
        is_recall_visible(
            note,
            [ContextRecallLifecycleStatus.SUPERSEDED],
        )
        is True
    )

    note.status = "error"
    note.index_status = ObsidianIndexStatus.ERROR.value
    assert is_recall_visible(note, [ContextRecallLifecycleStatus.ERROR]) is False

    note.status = ""
    note.index_status = ObsidianIndexStatus.INDEXED.value
    assert is_recall_visible(note, None) is True


def test_search_request_accepts_explicit_administrative_lifecycle_statuses() -> None:
    request = ContextSearchRequest.model_validate_json(
        dumps_json(
            {
                "query": "lifecycle",
                "include_lifecycle_statuses": ["SUPERSEDED", "ARCHIVED"],
            }
        )
    )

    assert request.include_lifecycle_statuses == ["SUPERSEDED", "ARCHIVED"]
