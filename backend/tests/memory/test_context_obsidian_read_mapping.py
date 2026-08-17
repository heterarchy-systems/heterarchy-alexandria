"""Regression coverage for Obsidian note-to-Context read mapping."""

from __future__ import annotations

import os

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from app.memory.application.context_service import ContextService
from app.memory.domain.event_enum.context_enums import ContextKind, RagStrategy
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.obsidian_search_source import (
    SqlAlchemyObsidianContextSearchSource,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


@asynccontextmanager
async def _temporary_database(path: Path) -> AsyncIterator[Database]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        yield database
    finally:
        await database.shutdown()


def test_implementation_history_legacy_kind_does_not_break_context_search(
    tmp_path: Path,
) -> None:
    """A non-Context implementation kind must map safely instead of failing recall."""

    async def scenario() -> tuple[list[str], list[ContextKind]]:
        async with (
            _temporary_database(tmp_path / "implementation-history-rag.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Graph-aware Context Retrieval",
                    body=(
                        "# Graph-aware Context Retrieval\n\n"
                        "implementation-history-recall-regression-token"
                    ),
                    alexandria_type=AlexandriaNoteType.IMPLEMENTATION_HISTORY,
                    note_id="implementation_history_recall_regression",
                    project="heterarchy-alexandria",
                    source="test",
                    frontmatter={
                        "scope": "PROJECT",
                        "kind": "IMPLEMENTATION",
                        "context_kind": "IMPLEMENTATION",
                    },
                )
            )
            service = ContextService(
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            pack = await service.search(
                query="implementation-history-recall-regression-token",
                strategy=RagStrategy.FTS_ONLY,
                limit=5,
                project="heterarchy-alexandria",
            )
            return (
                [match.context.id for match in pack.matches],
                [match.context.kind for match in pack.matches],
            )

    context_ids, kinds = anyio.run(scenario)

    assert context_ids == ["obsidian:implementation_history_recall_regression"]
    assert kinds == [ContextKind.MEMORY]
