"""Context RAG behavior tests for Obsidian-backed Alexandria notes."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from sqlalchemy import delete, event, func, select
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)
from tests.memory.context_seed import seed_context

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.integration.obsidian_canonical_context_gateway import (
    ObsidianCanonicalContextGateway,
)
from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextRecallFilter,
    ContextVectorRecall,
    validated_scope_identity,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    RagHealthState,
    RagStrategy,
)
from app.memory.infrastructure.models.context_models import ContextChunkORM
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_search_source import (
    SqlAlchemyObsidianContextSearchSource,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


class KeywordEmbeddingProvider(EmbeddingProvider):
    """Deterministic provider that maps test keywords to stable vectors."""

    @property
    def provider_name(self) -> str:
        return "KEYWORD_TEST"

    @property
    def model_name(self) -> str:
        return "keyword-test-model"

    @property
    def dimensions(self) -> int:
        return 384

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        if "semantic-target" in text or "query-alias" in text:
            vector[0] = 1.0
        elif "distractor" in text:
            vector[1] = 1.0
        else:
            vector[2] = 1.0
        return vector


class CapturingEmbeddingProvider(KeywordEmbeddingProvider):
    """Embedding provider that records canonical document input text."""

    def __init__(self) -> None:
        self.document_texts: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_texts.extend(texts)
        return super().embed_documents(texts)


class UpgradedPoolingEmbeddingProvider(KeywordEmbeddingProvider):
    """Provider fake with same model/dimension but a changed fingerprint."""

    @property
    def provider_version(self) -> str:
        return "pooling-upgrade-v2"

    @property
    def pooling_mode(self) -> str:
        return "mean-v2"


@asynccontextmanager
async def _temporary_database(path: Path) -> AsyncIterator[Database]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        yield database
    finally:
        await database.shutdown()


def test_context_rag_search_includes_obsidian_vault_fts_source(
    tmp_path: Path,
) -> None:
    """Context RAG should retrieve indexed Obsidian notes without duplicating data."""

    async def scenario() -> tuple[str, list[str], str]:
        async with (
            _temporary_database(tmp_path / "obsidian-rag.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            saved = await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Command Usage Handoff",
                    body=(
                        "# Command Usage Handoff\n\n"
                        "agent-remote command usage is dogfood-ready."
                    ),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="command_usage_handoff",
                    tags=["commands", "usage"],
                    project="omx-agent-adapter",
                    source="codex",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            pack = await service.search(
                query="command usage",
                strategy=RagStrategy.FTS_ONLY,
                limit=5,
                project="omx-agent-adapter",
            )

        return (
            saved.note_id,
            [match.context.id for match in pack.matches],
            pack.context_pack,
        )

    note_id, context_ids, context_pack = anyio.run(scenario)

    assert set(context_ids) == {f"obsidian:{note_id}"}
    assert "Command Usage Handoff" in context_pack
    assert "obsidian:" in context_pack


def test_obsidian_fts_exact_title_outranks_body_frequency(tmp_path: Path) -> None:
    """An exact note title should outrank a document that repeats query terms in body."""

    async def scenario() -> list[tuple[str, float | None]]:
        async with (
            _temporary_database(tmp_path / "obsidian-rag-title-rank.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Alexandria Memory Steward Contract",
                    body="# Contract\n\nCanonical lifecycle policy.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="memory_steward_contract",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Memory Steward Daily Health",
                    body=(
                        "# Daily Health\n\n"
                        + "Alexandria Memory Steward Contract health evidence. " * 3
                    ),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="memory_steward_daily_health",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            pack = await service.search(
                query="Alexandria Memory Steward Contract",
                strategy=RagStrategy.FTS_ONLY,
                limit=2,
                project="heterarchy-alexandria",
            )
            return [(match.context.title, match.fts_score) for match in pack.matches]

    ranked = anyio.run(scenario)

    assert ranked[0][0] == "Alexandria Memory Steward Contract", ranked
    assert any(title == "Memory Steward Daily Health" for title, _score in ranked)


def test_obsidian_fts_bulk_hydrates_ranked_candidates(tmp_path: Path) -> None:
    """FTS candidate hydration must use bounded queries instead of N+1 gets."""

    async def scenario() -> tuple[int, int, int]:
        async with _temporary_database(tmp_path / "obsidian-rag-bulk.db") as database:
            async with database.session() as write_session:
                obsidian_service = ObsidianService(
                    repository=SqlAlchemyObsidianIndexRepository(session=write_session),
                    vault_path=str(tmp_path / "vault"),
                    alexandria_root="Alexandria",
                    context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
                )
                for index in range(6):
                    await obsidian_service.save_note(
                        ObsidianSaveNote(
                            title=f"Bulk Recall Note {index}",
                            body=(
                                f"# Bulk Recall Note {index}\n\n"
                                "bulk-hydration-regression-token"
                            ),
                            alexandria_type=AlexandriaNoteType.CONTEXT,
                            note_id=f"bulk_recall_note_{index}",
                            project="heterarchy-alexandria",
                            frontmatter={"scope": "PROJECT"},
                        )
                    )
                await write_session.commit()

            recall = ContextFtsRecall(
                query="bulk-hydration-regression-token",
                recall_filter=ContextRecallFilter(
                    limit=5,
                    kind=None,
                    scope_identity=validated_scope_identity(
                        (ContextScope.PROJECT, ContextScope.GLOBAL),
                        "heterarchy-alexandria",
                        None,
                        None,
                        None,
                        None,
                    ),
                    lifecycle_statuses=None,
                ),
            )
            statement_count = 0

            def count_statement(*_args: object, **_kwargs: object) -> None:
                nonlocal statement_count
                statement_count += 1

            event.listen(
                database.engine.sync_engine,
                "before_cursor_execute",
                count_statement,
            )
            try:
                async with database.session() as search_session:
                    source = SqlAlchemyObsidianContextSearchSource(
                        session=search_session
                    )
                    matches = await source.search_fts(recall)
                    first_statement_count = statement_count
                    statement_count = 0
                    repeated_matches = await source.search_fts(recall)
            finally:
                event.remove(
                    database.engine.sync_engine,
                    "before_cursor_execute",
                    count_statement,
                )
            assert len(repeated_matches) == len(matches)
            return first_statement_count, statement_count, len(matches)

    first_statement_count, repeated_statement_count, match_count = anyio.run(scenario)

    assert first_statement_count == 3
    assert repeated_statement_count == 3
    assert match_count == 5


def test_obsidian_vector_bulk_hydrates_ranked_candidates(tmp_path: Path) -> None:
    """Vector candidate hydration must use one rank query and two bulk loads."""

    async def scenario() -> tuple[int, int]:
        async with _temporary_database(
            tmp_path / "obsidian-vector-bulk.db"
        ) as database:
            async with database.session() as write_session:
                obsidian_service = ObsidianService(
                    repository=SqlAlchemyObsidianIndexRepository(session=write_session),
                    vault_path=str(tmp_path / "vault"),
                    alexandria_root="Alexandria",
                    context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
                )
                provider = KeywordEmbeddingProvider()
                for index in range(6):
                    await obsidian_service.save_note(
                        ObsidianSaveNote(
                            title=f"Vector Recall Note {index}",
                            body=(
                                f"# Vector Recall Note {index}\n\n"
                                "semantic-target vector-bulk-regression-token"
                            ),
                            alexandria_type=AlexandriaNoteType.CONTEXT,
                            note_id=f"vector_recall_note_{index}",
                            project="heterarchy-alexandria",
                            frontmatter={"scope": "PROJECT"},
                        )
                    )
                service = ContextService(
                    retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                    repository=SqlAlchemyContextRepository(session=write_session),
                    embedding_provider=provider,
                    vector_retrieval_enabled=True,
                    extra_search_sources=[
                        SqlAlchemyObsidianContextSearchSource(session=write_session)
                    ],
                )
                await service.reindex_embeddings(limit=50, force=True)
                await write_session.commit()

            recall = ContextVectorRecall(
                query_embedding=tuple(provider.embed_query("query-alias")),
                model_name=provider.model_name,
                dimensions=provider.dimensions,
                fingerprint_key=provider.fingerprint().key(),
                recall_filter=ContextRecallFilter(
                    limit=5,
                    kind=None,
                    scope_identity=validated_scope_identity(
                        (ContextScope.PROJECT, ContextScope.GLOBAL),
                        "heterarchy-alexandria",
                        None,
                        None,
                        None,
                        None,
                    ),
                    lifecycle_statuses=None,
                ),
            )
            statement_count = 0

            def count_statement(*_args: object, **_kwargs: object) -> None:
                nonlocal statement_count
                statement_count += 1

            event.listen(
                database.engine.sync_engine,
                "before_cursor_execute",
                count_statement,
            )
            try:
                async with database.session() as search_session:
                    matches = await SqlAlchemyObsidianContextSearchSource(
                        session=search_session
                    ).search_vector(recall)
            finally:
                event.remove(
                    database.engine.sync_engine,
                    "before_cursor_execute",
                    count_statement,
                )
            return statement_count, len(matches)

    statement_count, match_count = anyio.run(scenario)

    assert statement_count == 3
    assert match_count == 5


def test_obsidian_embedding_input_includes_title_heading_and_content(
    tmp_path: Path,
) -> None:
    """Canonical Obsidian vectors should use the versioned metadata input format."""

    async def scenario() -> tuple[int, list[str]]:
        async with (
            _temporary_database(tmp_path / "obsidian-embedding-input.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Metadata Embedding Note",
                    body=(
                        "# Metadata Embedding Note\n\n"
                        "Overview.\n\n"
                        "## Retrieval Evidence\n\n"
                        "semantic-target canonical content."
                    ),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="metadata_embedding_note",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            provider = CapturingEmbeddingProvider()
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=provider,
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            rebuilt = await context_service.reindex_embeddings(limit=20, force=True)
            return rebuilt.updated, provider.document_texts

    updated, document_texts = anyio.run(scenario)

    assert updated >= 1
    assert any(
        document_text.startswith(
            "Title: Metadata Embedding Note\nHeading: Retrieval Evidence\n\n"
        )
        and "semantic-target canonical content." in document_text
        for document_text in document_texts
    )


def test_context_rag_excludes_librarian_ops_and_superseded_notes_by_default(
    tmp_path: Path,
) -> None:
    """Default Obsidian RAG should avoid operational and superseded recall noise."""

    async def scenario() -> list[str]:
        async with (
            _temporary_database(tmp_path / "obsidian-rag-visibility.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Canonical Librarian Policy",
                    body="# Canonical\n\nlibrarian-curation-policy durable guidance.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="canonical_librarian_policy",
                    project="heterarchy-alexandria",
                    status="active",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Librarian Chat Noise",
                    body="# Chat\n\nlibrarian-curation-policy operational transcript.",
                    alexandria_type=AlexandriaNoteType.LIBRARIAN_CHAT,
                    note_id="librarian_chat_noise",
                    relative_path="_Ops/Librarian/Chats/librarian_chat_noise.md",
                    project="heterarchy-alexandria",
                    status="active",
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Superseded Librarian Policy",
                    body="# Superseded\n\nlibrarian-curation-policy outdated draft.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="superseded_librarian_policy",
                    project="heterarchy-alexandria",
                    status="superseded",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Archived Librarian Policy",
                    body="# Archived\n\nlibrarian-curation-policy archived note.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="archived_librarian_policy",
                    project="heterarchy-alexandria",
                    status="archived",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            pack = await service.search(
                query="librarian-curation-policy",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                project="heterarchy-alexandria",
            )
            return [match.context.id for match in pack.matches]

    context_ids = anyio.run(scenario)

    assert context_ids == ["obsidian:canonical_librarian_policy"]


def test_obsidian_context_scope_identity_round_trip_filters_recall(
    tmp_path: Path,
) -> None:
    """Obsidian Context reindex should preserve scope identity for recall."""

    async def scenario() -> tuple[
        dict[str, str],
        dict[str, object],
        list[str],
        list[str],
        list[str],
        list[str],
    ]:
        async with (
            _temporary_database(tmp_path / "obsidian-scope-round-trip.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            fixtures = [
                ObsidianSaveNote(
                    title="A Agent Memory",
                    body="# A Agent Memory\n\nscope-round-trip-token agent A.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_agent_a",
                    project="agent-platform",
                    frontmatter={
                        "scope": "AGENT",
                        "agent_id": "hermes-coding",
                        "workspace_id": "default",
                        "visibility": "PROJECT",
                        "version": 3,
                        "provenance": {
                            "source_actor_id": "hermes-coding",
                            "source_actor_type": "AGENT",
                            "source_run_id": "run-001",
                            "external_run_id": "external-001",
                            "artifact_refs": ["artifact://test-results.json"],
                            "evidence_refs": ["context://decision-001"],
                            "confidence": "HIGH",
                        },
                    },
                ),
                ObsidianSaveNote(
                    title="B Agent Memory",
                    body="# B Agent Memory\n\nscope-round-trip-token agent B.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_agent_b",
                    project="agent-platform",
                    frontmatter={
                        "scope": "AGENT",
                        "agent_id": "hermes-research",
                        "workspace_id": "default",
                    },
                ),
                ObsidianSaveNote(
                    title="A Agent Other Workspace",
                    body=(
                        "# A Agent Other Workspace\n\n"
                        "scope-round-trip-token other workspace."
                    ),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_agent_a_other_workspace",
                    project="agent-platform",
                    frontmatter={
                        "scope": "AGENT",
                        "agent_id": "hermes-coding",
                        "workspace_id": "workspace-other",
                    },
                ),
                ObsidianSaveNote(
                    title="A Session Memory",
                    body="# A Session Memory\n\nscope-round-trip-token session A.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_session_a",
                    project="agent-platform",
                    frontmatter={
                        "scope": "SESSION",
                        "session_id": "session-a",
                        "workspace_id": "default",
                    },
                ),
                ObsidianSaveNote(
                    title="Shared Project Memory",
                    body="# Shared Project Memory\n\nscope-round-trip-token project.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_project_shared",
                    project="agent-platform",
                    frontmatter={
                        "scope": "PROJECT",
                        "workspace_id": "default",
                    },
                ),
            ]
            for fixture in fixtures:
                await obsidian_service.save_note(fixture)

            markdown_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "A Agent Memory.md"
            )
            markdown = markdown_path.read_text(encoding="utf-8")

            await session.execute(delete(ObsidianChunkORM))
            await session.execute(delete(ObsidianFileORM))
            await session.commit()
            reindex = await obsidian_service.reindex()

            indexed_rows = await session.scalars(
                select(ObsidianFileORM).order_by(ObsidianFileORM.note_id)
            )
            frontmatter_by_id = {
                row.note_id: row.frontmatter_json for row in indexed_rows.all()
            }
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=KeywordEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            await service.reindex_embeddings(limit=20, force=True)

            agent_pack = await service.search(
                query="scope-round-trip-token",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                project="agent-platform",
                agent_id="hermes-coding",
                workspace_id="default",
                include_scopes=[ContextScope.AGENT, ContextScope.PROJECT],
            )
            session_pack = await service.search(
                query="scope-round-trip-token",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                session_id="session-a",
                workspace_id="default",
                include_scopes=[ContextScope.SESSION],
            )
            vector_pack = await service.search(
                query="scope-round-trip-token",
                strategy=RagStrategy.VECTOR_ONLY,
                limit=10,
                project="agent-platform",
                agent_id="hermes-coding",
                workspace_id="default",
                include_scopes=[ContextScope.AGENT, ContextScope.PROJECT],
            )
            hybrid_pack = await service.search(
                query="scope-round-trip-token",
                strategy=RagStrategy.HYBRID,
                limit=10,
                project="agent-platform",
                agent_id="hermes-coding",
                workspace_id="default",
                include_scopes=[ContextScope.AGENT, ContextScope.PROJECT],
            )

        assert reindex.errors == ()
        assert "scope: AGENT" in markdown
        assert "agent_id: hermes-coding" in markdown
        assert frontmatter_by_id["ctx_agent_a"]["scope"] == "AGENT"
        assert frontmatter_by_id["ctx_agent_a"]["agent_id"] == "hermes-coding"
        assert frontmatter_by_id["ctx_agent_a"]["source_actor_id"] == "hermes-coding"
        assert frontmatter_by_id["ctx_agent_a"]["source_actor_type"] == "AGENT"
        assert frontmatter_by_id["ctx_agent_a"]["source_run_id"] == "run-001"
        assert frontmatter_by_id["ctx_agent_a"]["external_run_id"] == "external-001"
        assert frontmatter_by_id["ctx_agent_a"]["artifact_refs"] == [
            "artifact://test-results.json"
        ]
        assert frontmatter_by_id["ctx_agent_a"]["evidence_refs"] == [
            "context://decision-001"
        ]
        assert frontmatter_by_id["ctx_agent_a"]["confidence"] == "HIGH"
        assert frontmatter_by_id["ctx_agent_a"]["visibility"] == "PROJECT"
        assert frontmatter_by_id["ctx_agent_a"]["version"] == 3
        assert len(str(frontmatter_by_id["ctx_agent_a"]["content_hash"])) == 64
        agent_match = next(
            match
            for match in agent_pack.matches
            if match.context.id == "obsidian:ctx_agent_a"
        )
        return (
            {
                key: str(frontmatter_by_id["ctx_agent_a"][key])
                for key in (
                    "scope",
                    "workspace_id",
                    "agent_id",
                    "project",
                    "visibility",
                )
            },
            dict(agent_match.context.context_metadata),
            [match.context.id for match in agent_pack.matches],
            [match.context.id for match in session_pack.matches],
            [match.context.id for match in vector_pack.matches],
            [match.context.id for match in hybrid_pack.matches],
        )

    identity, metadata, agent_ids, session_ids, vector_ids, hybrid_ids = anyio.run(
        scenario
    )

    assert identity == {
        "scope": "AGENT",
        "workspace_id": "default",
        "agent_id": "hermes-coding",
        "project": "agent-platform",
        "visibility": "PROJECT",
    }
    assert metadata["lifecycle_status"] == "active"
    assert metadata["version"] == 3
    assert len(str(metadata["content_hash"])) == 64
    assert metadata["provenance"] == {
        "source_actor_id": "hermes-coding",
        "source_actor_type": "AGENT",
        "source_run_id": "run-001",
        "external_run_id": "external-001",
        "artifact_refs": ["artifact://test-results.json"],
        "evidence_refs": ["context://decision-001"],
        "confidence": "HIGH",
    }
    assert set(agent_ids) == {"obsidian:ctx_agent_a", "obsidian:ctx_project_shared"}
    assert session_ids == ["obsidian:ctx_session_a"]
    assert set(vector_ids) == {"obsidian:ctx_agent_a", "obsidian:ctx_project_shared"}
    assert set(hybrid_ids) == {"obsidian:ctx_agent_a", "obsidian:ctx_project_shared"}


def test_obsidian_scope_filter_runs_before_candidate_limit(
    tmp_path: Path,
) -> None:
    """Cross-scope candidates must not crowd valid results out of top-N recall."""

    async def scenario() -> dict[RagStrategy, list[str]]:
        async with (
            _temporary_database(tmp_path / "obsidian-scope-candidates.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            for index in range(12):
                await obsidian_service.save_note(
                    ObsidianSaveNote(
                        title=f"Distractor Agent {index}",
                        body="# Distractor\n\nscope-candidate-token exact match.",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id=f"ctx_distractor_{index}",
                        project="agent-platform",
                        frontmatter={
                            "scope": "AGENT",
                            "agent_id": "hermes-research",
                        },
                    )
                )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Target Agent",
                    body="# Target\n\nscope-candidate-token exact match.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_target_agent",
                    project="agent-platform",
                    frontmatter={
                        "scope": "AGENT",
                        "agent_id": "hermes-coding",
                    },
                )
            )
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=KeywordEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            await service.reindex_embeddings(limit=100, force=True)
            results: dict[RagStrategy, list[str]] = {}
            for strategy in RagStrategy.fixed():
                pack = await service.search(
                    query="scope-candidate-token",
                    strategy=strategy,
                    limit=1,
                    agent_id="hermes-coding",
                    include_scopes=[ContextScope.AGENT],
                )
                results[strategy] = [match.context.id for match in pack.matches]
        return results

    assert anyio.run(scenario) == {
        RagStrategy.FTS_ONLY: ["obsidian:ctx_target_agent"],
        RagStrategy.VECTOR_ONLY: ["obsidian:ctx_target_agent"],
        RagStrategy.HYBRID: ["obsidian:ctx_target_agent"],
    }


def test_obsidian_context_scope_identity_validation_blocks_invalid_save_and_reindex(
    tmp_path: Path,
) -> None:
    """Context scope identity validation should reject invalid saves and index rows."""

    async def scenario() -> tuple[list[str], list[bool], list[str]]:
        async with (
            _temporary_database(tmp_path / "obsidian-scope-validation.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            invalid_agent_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Invalid Agent Context.md"
            )
            invalid_project_path = invalid_agent_path.with_name(
                "Invalid Project Context.md"
            )
            save_errors: list[str] = []
            try:
                await obsidian_service.save_note(
                    ObsidianSaveNote(
                        title="Invalid Agent Context",
                        body="# Invalid\n\ninvalid-scope-token should not save.",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_invalid_agent_save",
                        project="agent-platform",
                        frontmatter={"scope": "AGENT"},
                    )
                )
            except ObsidianValidationError as exc:
                save_errors.append(str(exc))
            try:
                await obsidian_service.save_note(
                    ObsidianSaveNote(
                        title="Invalid Project Context",
                        body="# Invalid\n\nmissing project should not save.",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_invalid_project_save",
                        frontmatter={"scope": "PROJECT"},
                    )
                )
            except ObsidianValidationError as exc:
                save_errors.append(str(exc))

            reindex_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Invalid Session Context.md"
            )
            reindex_path.parent.mkdir(parents=True, exist_ok=True)
            reindex_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_invalid_session_reindex",
                        "alexandria_type: context",
                        "title: Invalid Session Context",
                        "status: active",
                        "scope: SESSION",
                        "project: agent-platform",
                        "---",
                        "",
                        "# Invalid Session Context",
                        "",
                        "invalid-scope-token should be an index error.",
                    ]
                ),
                encoding="utf-8",
            )
            invalid_status_path = reindex_path.with_name("Invalid Status Context.md")
            invalid_status_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_invalid_status_reindex",
                        "alexandria_type: context",
                        "title: Invalid Status Context",
                        "status: impossible",
                        "scope: PROJECT",
                        "project: agent-platform",
                        "---",
                        "",
                        "# Invalid Status Context",
                        "",
                        "invalid status should be an index error.",
                    ]
                ),
                encoding="utf-8",
            )
            invalid_provenance_path = reindex_path.with_name(
                "Invalid Provenance Context.md"
            )
            invalid_provenance_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_invalid_provenance_reindex",
                        "alexandria_type: context",
                        "title: Invalid Provenance Context",
                        "status: current",
                        "scope: PROJECT",
                        "project: agent-platform",
                        "provenance:",
                        "  source_actor_type: NOT_AN_ACTOR",
                        "---",
                        "",
                        "# Invalid Provenance Context",
                        "",
                        "invalid provenance should be an index error.",
                    ]
                ),
                encoding="utf-8",
            )
            result = await obsidian_service.reindex()
        return (
            save_errors,
            [invalid_agent_path.exists(), invalid_project_path.exists()],
            result.errors,
        )

    save_errors, invalid_save_exists, reindex_errors = anyio.run(scenario)

    assert any("MISSING_AGENT_ID" in error for error in save_errors)
    assert any("MISSING_PROJECT" in error for error in save_errors)
    assert invalid_save_exists == [False, False]
    assert len(reindex_errors) == 3
    assert any("MISSING_SESSION_ID" in error for error in reindex_errors)
    assert any("INVALID_STATUS" in error for error in reindex_errors)
    assert any("INVALID_PROVENANCE" in error for error in reindex_errors)


def test_obsidian_reindex_persists_structured_error_and_clears_it_after_repair(
    tmp_path: Path,
) -> None:
    """Operators should see invalid notes until a successful repair reindex."""

    async def scenario() -> tuple[
        ObsidianReindexResult,
        ObsidianVaultStatus,
        tuple[ObsidianReindexResult, ObsidianVaultStatus],
    ]:
        async with (
            _temporary_database(tmp_path / "obsidian-index-errors.db") as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            note_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Repairable Session.md"
            )
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_repairable_session",
                        "alexandria_type: context",
                        "title: Repairable Session",
                        "status: current",
                        "scope: SESSION",
                        "---",
                        "",
                        "# Repairable Session",
                    ]
                ),
                encoding="utf-8",
            )
            failed_reindex = await service.reindex()
            failed_status = await service.status()

            note_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_repairable_session",
                        "alexandria_type: context",
                        "title: Repairable Session",
                        "status: current",
                        "scope: SESSION",
                        "session_id: session-a",
                        "---",
                        "",
                        "# Repairable Session",
                    ]
                ),
                encoding="utf-8",
            )
            repaired_reindex = await service.reindex()
            repaired_status = await service.status()
        return failed_reindex, failed_status, (repaired_reindex, repaired_status)

    failed_reindex, failed_status, repaired = anyio.run(scenario)
    repaired_reindex, repaired_status = repaired

    assert failed_status.error_notes == 1
    assert failed_status.index_errors == failed_reindex.error_details
    assert failed_reindex.error_details[0].context_id == "ctx_repairable_session"
    assert failed_reindex.error_details[0].error_code == "MISSING_SESSION_ID"
    assert failed_reindex.error_details[0].note_path.endswith("Repairable Session.md")
    assert repaired_reindex.errors == ()
    assert repaired_status.error_notes == 0
    assert repaired_status.index_errors == ()


def test_obsidian_index_error_does_not_overwrite_valid_duplicate_context_id(
    tmp_path: Path,
) -> None:
    """An invalid duplicate id must not replace the valid indexed Context row."""

    async def scenario() -> tuple[str, str | None, int]:
        async with (
            _temporary_database(
                tmp_path / "obsidian-error-id-collision.db"
            ) as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            valid = await service.save_note(
                ObsidianSaveNote(
                    title="Valid Context",
                    body="# Valid Context\n\nvalid duplicate-id content",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_shared_id",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            invalid_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Z Invalid Duplicate.md"
            )
            invalid_path.write_text(
                "\n".join(
                    [
                        "---",
                        "id: ctx_shared_id",
                        "alexandria_type: context",
                        "title: Invalid Duplicate",
                        "status: current",
                        "scope: AGENT",
                        "---",
                        "",
                        "# Invalid Duplicate",
                    ]
                ),
                encoding="utf-8",
            )
            await service.reindex()
            valid_after = await service.read_note_by_path(valid.relative_path)
            status = await service.status()
        return (
            valid_after.note_id,
            status.index_errors[0].context_id,
            status.error_notes,
        )

    valid_id, error_context_id, error_count = anyio.run(scenario)

    assert valid_id == "ctx_shared_id"
    assert error_context_id == "ctx_shared_id"
    assert error_count == 1


def test_obsidian_reindex_reports_two_valid_paths_with_the_same_context_id(
    tmp_path: Path,
) -> None:
    """Full reindex must retain one valid row and report the duplicate path."""

    async def scenario() -> tuple[list[str], list[str], int]:
        async with (
            _temporary_database(
                tmp_path / "obsidian-valid-id-collision.db"
            ) as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            root = tmp_path / "vault" / "Alexandria" / "Contexts" / "Projects"
            root.mkdir(parents=True, exist_ok=True)
            for title in ("A First", "B Duplicate"):
                (root / f"{title}.md").write_text(
                    "\n".join(
                        [
                            "---",
                            "id: ctx_duplicate_reindex",
                            "alexandria_type: context",
                            f"title: {title}",
                            "status: current",
                            "scope: PROJECT",
                            "project: agent-platform",
                            "---",
                            "",
                            f"# {title}",
                        ]
                    ),
                    encoding="utf-8",
                )
            result = await service.reindex()
            indexed = await service.read_note_by_path(
                "Alexandria/Contexts/Projects/A First.md"
            )
            status = await service.status()
        return (
            result.errors,
            [error.error_code for error in status.index_errors],
            1 if indexed.note_id == "ctx_duplicate_reindex" else 0,
        )

    errors, error_codes, retained = anyio.run(scenario)

    assert any("DUPLICATE_CONTEXT_ID" in error for error in errors)
    assert error_codes == ["DUPLICATE_CONTEXT_ID"]
    assert retained == 1


def test_obsidian_context_update_cannot_duplicate_another_context(
    tmp_path: Path,
) -> None:
    """Updating a path to duplicate content must preserve both canonical files."""

    async def scenario() -> tuple[str, str]:
        async with (
            _temporary_database(tmp_path / "obsidian-update-duplicate.db") as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await service.save_note(
                ObsidianSaveNote(
                    title="First Context",
                    body="# Shared\n\nduplicate update body",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_update_first",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            second = await service.save_note(
                ObsidianSaveNote(
                    title="Second Context",
                    body="# Distinct\n\noriginal second body",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_update_second",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            duplicate = await service.save_note(
                ObsidianSaveNote(
                    title=second.title,
                    body="# Shared\n\nduplicate update body",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id=second.note_id,
                    relative_path=second.relative_path,
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            second_after = await service.read_note_by_path(second.relative_path)
        return duplicate.note_id, second_after.body

    duplicate_id, second_body = anyio.run(scenario)

    assert duplicate_id == "ctx_update_first"
    assert "original second body" in second_body


def test_obsidian_context_duplicate_and_supersede_lifecycle(
    tmp_path: Path,
) -> None:
    """Canonical Context saves should deduplicate and preserve supersede history."""

    async def scenario() -> tuple[str, str, str, str, list[str], list[str]]:
        async with (
            _temporary_database(tmp_path / "obsidian-context-lifecycle.db") as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            old = await service.save_note(
                ObsidianSaveNote(
                    title="Original Decision",
                    body="# Original\n\ndurable-supersede-token original content.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_original",
                    status="current",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            duplicate = await service.save_note(
                ObsidianSaveNote(
                    title="Duplicate Decision",
                    body="# Original\n\ndurable-supersede-token original content.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_duplicate",
                    status="current",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            replacement = await service.save_note(
                ObsidianSaveNote(
                    title="Replacement Decision",
                    body="# Replacement\n\ndurable-supersede-token replacement content.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_replacement",
                    status="current",
                    project="agent-platform",
                    frontmatter={
                        "scope": "PROJECT",
                        "supersedes_context_id": "ctx_original",
                    },
                )
            )
            original_after = await service.read_note_by_path(old.relative_path)
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            recall = await context_service.search(
                query="durable-supersede-token",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                project="agent-platform",
                include_scopes=[ContextScope.PROJECT],
            )
            duplicate_path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Duplicate Decision.md"
            )
        return (
            old.note_id,
            duplicate.note_id,
            replacement.note_id,
            original_after.body,
            [match.context.id for match in recall.matches],
            [str(duplicate_path.exists()), original_after.status],
        )

    old_id, duplicate_id, replacement_id, old_body, recall_ids, lifecycle = anyio.run(
        scenario
    )

    assert duplicate_id == old_id
    assert replacement_id == "ctx_replacement"
    assert "original content" in old_body
    assert recall_ids == ["obsidian:ctx_replacement"]
    assert lifecycle == ["False", "superseded"]


def test_explicit_supersede_excludes_old_context_from_default_recall(
    tmp_path: Path,
) -> None:
    """Explicit supersede must immediately enforce the default recall boundary."""

    async def scenario() -> list[str]:
        async with (
            _temporary_database(tmp_path / "explicit-supersede-recall.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Explicit Recall Old",
                    body="# Old\n\nexplicit-recall-token old decision",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_explicit_recall_old",
                    status="current",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Explicit Recall New",
                    body="# New\n\nexplicit-recall-token replacement decision",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_explicit_recall_new",
                    status="current",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.supersede_context(
                "ctx_explicit_recall_old",
                "ctx_explicit_recall_new",
            )
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            recall = await context_service.search(
                query="explicit-recall-token",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                project="agent-platform",
                include_scopes=[ContextScope.PROJECT],
            )
            return [match.context.id for match in recall.matches]

    recall_ids = anyio.run(scenario)

    assert recall_ids == ["obsidian:ctx_explicit_recall_new"]


def test_obsidian_context_supersede_rejects_self_and_missing_target(
    tmp_path: Path,
) -> None:
    """Supersede references must point to a different existing Context."""

    async def scenario() -> tuple[list[str], list[bool]]:
        async with (
            _temporary_database(tmp_path / "obsidian-invalid-supersede.db") as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            errors: list[str] = []
            titles = ("Self Supersede", "Missing Supersede")
            references = ("ctx_self", "ctx_missing")
            note_ids = ("ctx_self", "ctx_replacement")
            for title, reference, note_id in zip(
                titles,
                references,
                note_ids,
                strict=True,
            ):
                try:
                    await service.save_note(
                        ObsidianSaveNote(
                            title=title,
                            body=f"# {title}",
                            alexandria_type=AlexandriaNoteType.CONTEXT,
                            note_id=note_id,
                            status="current",
                            project="agent-platform",
                            frontmatter={
                                "scope": "PROJECT",
                                "supersedes_context_id": reference,
                            },
                        )
                    )
                except ObsidianValidationError as exc:
                    errors.append(str(exc))
            expected_paths = [
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / f"{title}.md"
                for title in titles
            ]
        return errors, [path.exists() for path in expected_paths]

    errors, files_exist = anyio.run(scenario)

    assert len(errors) == 2
    assert all("INVALID_SUPERSEDE" in error for error in errors)
    assert files_exist == [False, False]


def test_obsidian_context_rejects_conflicting_replacement_before_writing(
    tmp_path: Path,
) -> None:
    """A second replacement must fail before creating a new canonical note."""

    async def scenario() -> tuple[str, bool]:
        async with (
            _temporary_database(
                tmp_path / "obsidian-conflicting-supersede.db"
            ) as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await service.save_note(
                ObsidianSaveNote(
                    title="Original Context",
                    body="# Original\n\nconflict-safe content",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_conflict_original",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await service.save_note(
                ObsidianSaveNote(
                    title="First Replacement",
                    body="# First Replacement\n\nfirst replacement",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_first_replacement",
                    project="agent-platform",
                    frontmatter={
                        "scope": "PROJECT",
                        "supersedes_context_id": "ctx_conflict_original",
                    },
                )
            )
            error = ""
            try:
                await service.save_note(
                    ObsidianSaveNote(
                        title="Second Replacement",
                        body="# Second Replacement\n\nsecond replacement",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        note_id="ctx_second_replacement",
                        project="agent-platform",
                        frontmatter={
                            "scope": "PROJECT",
                            "supersedes_context_id": "ctx_conflict_original",
                        },
                    )
                )
            except ObsidianValidationError as exc:
                error = str(exc)
            path = (
                tmp_path
                / "vault"
                / "Alexandria"
                / "Contexts"
                / "Projects"
                / "Second Replacement.md"
            )
        return error, path.exists()

    error, file_exists = anyio.run(scenario)

    assert "INVALID_SUPERSEDE" in error
    assert file_exists is False


def test_obsidian_context_supersede_exact_retry_is_idempotent(tmp_path: Path) -> None:
    """Retrying the same replacement must not increment the old version again."""

    async def scenario() -> tuple[int, int]:
        async with (
            _temporary_database(tmp_path / "obsidian-supersede-retry.db") as database,
            database.session() as session,
        ):
            service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await service.save_note(
                ObsidianSaveNote(
                    title="Retry Original",
                    body="# Original\n\nretry original",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_retry_original",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            replacement = ObsidianSaveNote(
                title="Retry Replacement",
                body="# Replacement\n\nretry replacement",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                note_id="ctx_retry_replacement",
                project="agent-platform",
                frontmatter={
                    "scope": "PROJECT",
                    "supersedes_context_id": "ctx_retry_original",
                },
            )
            await service.save_note(replacement)
            first = await service.read_note("ctx_retry_original")
            await service.save_note(replacement)
            second = await service.read_note("ctx_retry_original")
        return int(first.frontmatter["version"]), int(second.frontmatter["version"])

    first_version, second_version = anyio.run(scenario)

    assert first_version == 2
    assert second_version == first_version


def test_context_rag_returns_one_best_chunk_per_obsidian_note(
    tmp_path: Path,
) -> None:
    """Context packs should not spend the result budget on duplicate note chunks."""

    async def scenario() -> list[str]:
        async with (
            _temporary_database(tmp_path / "obsidian-rag-dedupe.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Multi Chunk Librarian Playbook",
                    body=(
                        "# First\n\ncontext-dedupe-token first guidance.\n\n"
                        "# Second\n\ncontext-dedupe-token second guidance.\n\n"
                        "# Third\n\ncontext-dedupe-token third guidance."
                    ),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="multi_chunk_librarian_playbook",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Single Chunk Librarian Playbook",
                    body="# Single\n\ncontext-dedupe-token separate guidance.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="single_chunk_librarian_playbook",
                    project="heterarchy-alexandria",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            pack = await service.search(
                query="context-dedupe-token",
                strategy=RagStrategy.FTS_ONLY,
                limit=10,
                project="heterarchy-alexandria",
            )
            return [match.context.id for match in pack.matches]

    context_ids = anyio.run(scenario)

    assert context_ids.count("obsidian:multi_chunk_librarian_playbook") == 1
    assert context_ids.count("obsidian:single_chunk_librarian_playbook") == 1
    assert len(context_ids) == 2


def test_context_embedding_reindex_backfills_obsidian_chunks_for_vector_search(
    tmp_path: Path,
) -> None:
    """Context embedding reindex should make Obsidian chunks vector-searchable."""

    async def scenario() -> tuple[int, int, list[str]]:
        async with (
            _temporary_database(tmp_path / "obsidian-vector-rag.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Semantic Target Note",
                    body="# Semantic Target\n\nsemantic-target belongs to the vault.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="semantic_target_note",
                    project="omx-agent-adapter",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Distractor Note",
                    body="# Distractor\n\ndistractor belongs elsewhere.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="distractor_note",
                    project="omx-agent-adapter",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=KeywordEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )

            before = await service.search(
                query="query-alias",
                strategy=RagStrategy.VECTOR_ONLY,
                limit=1,
                project="omx-agent-adapter",
            )
            result = await service.reindex_embeddings(limit=10)
            after = await service.search(
                query="query-alias",
                strategy=RagStrategy.VECTOR_ONLY,
                limit=1,
                project="omx-agent-adapter",
            )

        assert before.matches == ()
        return (
            result.scanned,
            result.updated,
            [match.context.id for match in after.matches],
        )

    scanned, updated, context_ids = anyio.run(scenario)

    assert scanned >= 2
    assert updated >= 2
    assert context_ids == ["obsidian:semantic_target_note"]


def test_context_rag_status_detects_obsidian_embedding_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    """Obsidian source vectors should be blocked until fingerprint reindex runs."""

    async def scenario() -> tuple[str, str, int, list[str], list[str | None]]:
        async with (
            _temporary_database(tmp_path / "obsidian-fingerprint-rag.db") as database,
            database.session() as session,
        ):
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Semantic Target Note",
                    body="# Semantic Target\n\nsemantic-target belongs to the vault.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="semantic_target_note",
                    project="omx-agent-adapter",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            old_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=KeywordEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            await old_service.reindex_embeddings(limit=10)

            upgraded_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=UpgradedPoolingEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
            )
            health = await upgraded_service.rag_health_with_index_status()
            before = await upgraded_service.search(
                query="query-alias",
                strategy=RagStrategy.VECTOR_ONLY,
                limit=1,
                project="omx-agent-adapter",
            )
            rebuilt = await upgraded_service.reindex_embeddings(limit=10)
            after = await upgraded_service.search(
                query="query-alias",
                strategy=RagStrategy.VECTOR_ONLY,
                limit=1,
                project="omx-agent-adapter",
            )
            chunks = await session.scalars(select(ObsidianChunkORM))

        return (
            health.embedding.value,
            before.effective_strategy.value,
            rebuilt.updated,
            [match.context.id for match in after.matches],
            [chunk.embedding_pooling_mode for chunk in chunks.all()],
        )

    health_status, before_strategy, updated, context_ids, pooling_modes = anyio.run(
        scenario
    )

    assert health_status == RagHealthState.REINDEX_REQUIRED.value
    assert before_strategy == RagStrategy.FTS_ONLY.value
    assert updated >= 1
    assert context_ids == ["obsidian:semantic_target_note"]
    assert "mean-v2" in pooling_modes


def test_context_soft_rebuild_reports_and_prioritizes_stale_obsidian_source(
    tmp_path: Path,
) -> None:
    """Soft rebuild batches should update stale sources before current chunks."""

    async def scenario() -> tuple[
        int,
        str,
        list[str | None],
        list[str | None],
        dict[str, tuple[int, int, int]],
        dict[str, tuple[int, int, int]],
    ]:
        async with (
            _temporary_database(tmp_path / "cross-source-soft-rebuild.db") as database,
            database.session() as session,
        ):
            repository = SqlAlchemyContextRepository(session=session)
            obsidian_source = SqlAlchemyObsidianContextSearchSource(session=session)
            obsidian_service = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Stale Obsidian Target",
                    body="# Semantic Target\n\nsemantic-target belongs to the vault.",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="stale_obsidian_target",
                    project="omx-agent-adapter",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            old_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=repository,
                embedding_provider=KeywordEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[obsidian_source],
            )
            await old_service.reindex_embeddings(limit=10)

            await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Current Context Target",
                summary="Already matches the upgraded fingerprint.",
                content="# Current Context\n\nsemantic-target already current.",
                project="omx-agent-adapter",
                embedding_provider=UpgradedPoolingEmbeddingProvider(),
            )
            await session.commit()

            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=repository,
                embedding_provider=UpgradedPoolingEmbeddingProvider(),
                vector_retrieval_enabled=True,
                extra_search_sources=[obsidian_source],
            )
            report = await service.soft_rebuild_embeddings(limit=1)
            context_chunks = await session.scalars(select(ContextChunkORM))
            obsidian_chunks = await session.scalars(
                select(ObsidianChunkORM).where(
                    func.length(func.trim(ObsidianChunkORM.text)) > 0
                )
            )

        return (
            report.reindex.updated,
            report.after.embedding.value,
            [chunk.embedding_pooling_mode for chunk in context_chunks.all()],
            [chunk.embedding_pooling_mode for chunk in obsidian_chunks.all()],
            {
                status.source_name: (
                    status.total_rows,
                    status.current_rows,
                    status.stale_rows,
                )
                for status in report.source_status_before
            },
            {
                status.source_name: (
                    status.total_rows,
                    status.current_rows,
                    status.stale_rows,
                )
                for status in report.source_status_after
            },
        )

    (
        updated,
        after_status,
        context_pooling,
        obsidian_pooling,
        source_status_before,
        source_status_after,
    ) = anyio.run(scenario)

    assert updated == 1
    assert after_status == RagHealthState.HEALTHY.value
    assert context_pooling == ["mean-v2"]
    assert obsidian_pooling == ["mean-v2"]
    assert source_status_before["context_vault"] == (1, 1, 0)
    assert source_status_before["obsidian_vault"] == (1, 0, 1)
    assert source_status_after["context_vault"] == (1, 1, 0)
    assert source_status_after["obsidian_vault"] == (1, 1, 0)


def test_context_service_get_and_archive_source_qualified_obsidian_context(
    tmp_path: Path,
) -> None:
    """Search result IDs must support canonical GET and soft-delete archive."""

    async def scenario() -> tuple[str, str, str, bool, str, list[str]]:
        async with (
            _temporary_database(tmp_path / "obsidian-canonical-context.db") as database,
            database.session() as session,
        ):
            index_repository = SqlAlchemyObsidianIndexRepository(session=session)
            obsidian_service = ObsidianService(
                repository=index_repository,
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            await obsidian_service.save_note(
                ObsidianSaveNote(
                    title="Canonical Context",
                    body="# Canonical\n\nsource-qualified-context-token",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    note_id="ctx_canonical",
                    status="current",
                    project="agent-platform",
                    frontmatter={"scope": "PROJECT"},
                )
            )
            canonical_repository = ObsidianCanonicalContextGateway(obsidian_service)
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                extra_search_sources=[
                    SqlAlchemyObsidianContextSearchSource(session=session)
                ],
                canonical_context_repository=canonical_repository,
            )
            fetched = await context_service.get("obsidian:ctx_canonical")
            archived = await context_service.archive("obsidian:ctx_canonical")
            canonical = await obsidian_service.read_note("ctx_canonical")
            recall = await context_service.search(
                query="source-qualified-context-token",
                strategy=RagStrategy.FTS_ONLY,
                project="agent-platform",
                include_scopes=[ContextScope.PROJECT],
            )
            path_exists = (tmp_path / "vault" / canonical.relative_path).exists()
        return (
            fetched.id,
            archived.id,
            canonical.status,
            path_exists,
            str(archived.context_metadata["lifecycle_status"]),
            [match.context.id for match in recall.matches],
        )

    fetched_id, archived_id, status, path_exists, lifecycle_status, recall_ids = (
        anyio.run(scenario)
    )

    assert fetched_id == "obsidian:ctx_canonical"
    assert archived_id == fetched_id
    assert status == "archived"
    assert path_exists is True
    assert lifecycle_status == "archived"
    assert recall_ids == []
