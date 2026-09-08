"""Real PostgreSQL retrieval evidence for high-level recall routing."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast

import anyio
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)
from tests.memory.context_seed import seed_context
from tests.memory.test_context_repository import KeywordEmbeddingProvider
from tests.memory.test_high_level_recall import _ExactEmpty, _TemporalFake

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.retrieval.recall_service import RecallService
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.memory_reconciliation import (
    MemoryTemporalRecallPack,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    RagStrategy,
)
from app.memory.domain.event_enum.recall_enums import (
    RecallOutcome,
    RecallProjectAffinity,
    RecallRoute,
    RecallScopeMode,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.infrastructure.database import Database


@asynccontextmanager
async def _database() -> AsyncIterator[Database]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        yield database
    finally:
        await database.shutdown()


def _recall_service(context_service: ContextService) -> RecallService:
    """Build the real Context retrieval path with inert unused temporal wiring."""
    temporal = _TemporalFake(
        MemoryTemporalRecallPack(
            query="",
            mode=MemoryTemporalRecallMode.CURRENT,
            as_of=None,
            strategy=RagStrategy.HYBRID,
            effective_strategy=RagStrategy.HYBRID,
            warnings=(),
            recall_scopes=(ContextScope.GLOBAL,),
            matches=(),
            context_pack="",
        )
    )
    return RecallService(
        context_service=context_service,
        temporal_recall_service=cast(MemoryTemporalRecallService, temporal),
        exact_selector_resolver=_ExactEmpty(),
    )


def test_real_postgres_semantic_fallback_and_related_project_expansion() -> None:
    """FTS-empty paraphrase reaches vector search and related project routing."""

    async def scenario() -> tuple[
        RecallOutcome,
        RecallOutcome,
        list[RecallRoute],
        str,
        str,
    ]:
        provider = KeywordEmbeddingProvider()
        async with _database() as database, database.session() as session:
            repository = SqlAlchemyContextRepository(session=session)
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=repository,
                embedding_provider=provider,
                vector_retrieval_enabled=True,
            )
            primary = await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Current architecture decision",
                summary="A semantic retrieval target.",
                content="# Current architecture\n\nsemantic-target evidence.",
                project="alexandria",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            related = await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Forge defect evidence",
                summary="A related project semantic target.",
                content="# Forge defect\n\nsemantic-target evidence.",
                project="forge",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            await session.commit()

            service = _recall_service(context_service)
            primary_result = await service.recall(
                RecallRequest(
                    query="query-alias",
                    project="alexandria",
                    scope_mode=RecallScopeMode.AUTO,
                )
            )
            related_result = await service.recall(
                RecallRequest(
                    query="query-alias",
                    project="missing-primary",
                    related_projects=("forge",),
                    scope_mode=RecallScopeMode.AUTO,
                )
            )
            return (
                primary_result.outcome,
                related_result.outcome,
                [item.provenance.route for item in related_result.matches],
                f"{primary.id}:{related.id}",
                related_result.matches[0].provenance.project_affinity.value,
            )

    outcome, related_outcome, routes, ids, affinity = anyio.run(scenario)
    assert outcome is RecallOutcome.MATCHED
    assert related_outcome is RecallOutcome.MATCHED
    assert (
        RecallRoute.PRIMARY_SEMANTIC in routes
        or RecallRoute.RELATED_PROJECT_SEMANTIC in routes
    )
    assert affinity == RecallProjectAffinity.RELATED.value
    assert ids


def test_real_postgres_current_recall_filters_superseded_context() -> None:
    """Default high-level recall applies current temporal authority before stopping."""

    async def scenario() -> tuple[tuple[str, ...], str]:
        provider = KeywordEmbeddingProvider()
        async with _database() as database, database.session() as session:
            context_service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
                embedding_provider=provider,
                vector_retrieval_enabled=True,
            )
            old = await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Old architecture decision",
                summary="Superseded semantic target.",
                content="# Old architecture\n\nsemantic-target evidence.",
                project="alexandria",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            current = await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="Current architecture decision",
                summary="Current semantic target.",
                content="# Current architecture\n\nsemantic-target evidence.",
                project="alexandria",
                scope=ContextScope.PROJECT,
                embedding_provider=provider,
            )
            await session.commit()
            temporal_repository = SqlAlchemyMemoryReconciliationRepository(session)
            await temporal_repository.upsert_temporal_state(
                MemoryTemporalState(
                    context_id=old.id,
                    recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
                    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                    valid_to=datetime(2026, 7, 1, tzinfo=UTC),
                    is_current=False,
                    superseded_by=(current.id,),
                )
            )
            await temporal_repository.upsert_temporal_state(
                MemoryTemporalState(
                    context_id=current.id,
                    recorded_at=datetime(2026, 7, 2, tzinfo=UTC),
                    observed_at=datetime(2026, 7, 2, tzinfo=UTC),
                    valid_from=datetime(2026, 7, 2, tzinfo=UTC),
                    valid_to=None,
                    is_current=True,
                    supersedes=(old.id,),
                )
            )
            await session.commit()
            temporal_service = MemoryTemporalRecallService(
                context_service=context_service,
                repository=temporal_repository,
            )
            recall = RecallService(
                context_service=context_service,
                temporal_recall_service=temporal_service,
                exact_selector_resolver=_ExactEmpty(),
            )
            result = await recall.recall(
                RecallRequest(
                    query="query-alias",
                    project="alexandria",
                    scope_mode=RecallScopeMode.AUTO,
                )
            )
            return tuple(item.match.context.id for item in result.matches), current.id

    match_ids, current_id = anyio.run(scenario)
    assert match_ids == (current_id,)
