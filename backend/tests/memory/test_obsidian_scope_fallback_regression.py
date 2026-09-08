"""Real PostgreSQL/Vault regressions for non-Context scope fallback parity."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)
from tests.memory.test_context_obsidian_rag_source import KeywordEmbeddingProvider

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_search_source import (
    SqlAlchemyObsidianContextSearchSource,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models import obsidian_index_models as _models_loaded
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.infrastructure.database import Database

_MODELS_LOADED = _models_loaded


def test_non_context_missing_scope_reaches_project_fts_vector_and_hybrid_recall(
    tmp_path: Path,
) -> None:
    """Non-Context source notes derive PROJECT/GLOBAL lanes only in SQL recall."""

    async def scenario() -> tuple[list[str], list[str], list[str], list[str]]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        provider = KeywordEmbeddingProvider()
        try:
            obsidian = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
            )
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Implementation History Missing Scope",
                    body=(
                        "# Implementation History Missing Scope\n\n"
                        "projectrecalltoken semantic-target"
                    ),
                    alexandria_type=AlexandriaNoteType.IMPLEMENTATION_HISTORY,
                    note_id="history_missing_scope",
                    project="heterarchy-alexandria",
                    source="test",
                )
            )
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Global Job Plan Missing Scope",
                    body="# Global Job Plan Missing Scope\n\nglobalrecalltoken",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    note_id="global_missing_scope",
                    source="test",
                )
            )
            await obsidian.save_note(
                ObsidianSaveNote(
                    title="Private User Context",
                    body="# Private User Context\n\nprivateusertoken",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="private_user_context",
                    project="heterarchy-alexandria",
                    source="test",
                    frontmatter={
                        "scope": "USER",
                        "user_id": "private-user",
                    },
                )
            )
            await _insert_malformed_context(session, tmp_path)
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=provider,
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            await service.reindex_embeddings(limit=50, force=True)
            await session.commit()
            project_fts = await service.search(
                query="projectrecalltoken",
                strategy=RagStrategy.FTS_ONLY,
                project="heterarchy-alexandria",
                limit=10,
            )
            global_fts = await service.search(
                query="globalrecalltoken",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
            )
            project_hybrid = await service.search(
                query="query-alias",
                strategy=RagStrategy.HYBRID,
                project="heterarchy-alexandria",
                limit=10,
            )
            leaked_user = await service.search(
                query="privateusertoken",
                strategy=RagStrategy.FTS_ONLY,
                project="heterarchy-alexandria",
                limit=10,
            )
            private_user = await service.search(
                query="privateusertoken",
                strategy=RagStrategy.FTS_ONLY,
                include_scopes=[ContextScope.USER],
                user_id="private-user",
                limit=10,
            )
            return (
                [match.context.id for match in project_fts.matches],
                [match.context.id for match in global_fts.matches],
                [match.context.id for match in project_hybrid.matches],
                [match.context.id for match in leaked_user.matches]
                + [match.context.id for match in private_user.matches],
            )
        finally:
            await session.close()
            await database.shutdown()

    project_ids, global_ids, hybrid_ids, user_ids = anyio.run(scenario)

    assert project_ids == ["obsidian:history_missing_scope"]
    assert global_ids == ["obsidian:global_missing_scope"]
    assert "obsidian:history_missing_scope" in hybrid_ids
    assert "obsidian:malformed_context_missing_scope" not in hybrid_ids
    assert user_ids == ["obsidian:private_user_context"]
    assert "obsidian:malformed_context_missing_scope" not in project_ids


async def _insert_malformed_context(session, tmp_path: Path) -> None:
    """Insert a legacy malformed Context row without relaxing SQL scope policy."""
    del tmp_path
    now = datetime.now(UTC)
    body = "# Malformed Context\n\nscope-fallback-malformed"
    session.add(
        ObsidianFileORM(
            note_id="malformed_context_missing_scope",
            relative_path="Alexandria/Contexts/Malformed Scope.md",
            alexandria_type=AlexandriaNoteType.CONTEXT.value,
            title="Malformed Context",
            status="active",
            tags=[],
            project="heterarchy-alexandria",
            source="test",
            content_hash=hash_text(body),
            frontmatter_json={
                "id": "malformed_context_missing_scope",
                "alexandria_type": AlexandriaNoteType.CONTEXT.value,
                "title": "Malformed Context",
                "status": "active",
                "project": "heterarchy-alexandria",
            },
            body=body,
            index_status="indexed",
            error_message=None,
            size_bytes=len(body.encode("utf-8")),
            modified_at=now,
            indexed_at=now,
        )
    )
    await session.flush()
    session.add(
        ObsidianChunkORM(
            note_id="malformed_context_missing_scope",
            chunk_index=0,
            heading_path=None,
            text=body,
            token_count=4,
            content_hash=hash_text(body),
            created_at=now,
        )
    )
    await session.flush()
