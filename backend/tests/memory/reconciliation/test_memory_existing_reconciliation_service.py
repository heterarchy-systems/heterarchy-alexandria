"""Application tests for existing-memory reconciliation and temporal backfill."""

from __future__ import annotations

import os

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import anyio
from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.runtime.memory_existing_reconciliation_service import (
    MemoryExistingReconciliationService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.domain.contracts.memory_existing_reconciliation_contracts import (
    ExistingMemoryReconciliationRequest,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import CanonicalClaim
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryClaimPolarity,
    MemoryRelationType,
)
from app.memory.domain.repositories.contexts.memory_candidate_recall_source import (
    IMemoryCandidateRecallSource,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.infrastructure.database import Database
from pydantic import TypeAdapter

NOW = datetime(2026, 7, 25, tzinfo=UTC)
_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])


class StaticContextService:
    """Return filtered pages of prebuilt canonical Context read models."""

    def __init__(self, contexts: list[ContextRecord]) -> None:
        self._contexts = contexts
        self.calls: list[tuple[int, int, str | None, ContextScope | None, bool]] = []

    async def list_contexts(
        self,
        *,
        limit: int,
        offset: int,
        project: str | None,
        scope: ContextScope | None,
        include_archived: bool,
    ) -> tuple[list[ContextRecord], int]:
        self.calls.append((limit, offset, project, scope, include_archived))
        matches = [
            context
            for context in self._contexts
            if (project is None or context.project == project)
            and (scope is None or context.scope is scope)
            and (include_archived or not context.is_archived)
        ]
        return matches[offset : offset + limit], len(matches)


class StaticRecallSource(IMemoryCandidateRecallSource):
    """Return a fixed Context pack while recording bounded recall requests."""

    def __init__(self, pack: ContextPack) -> None:
        self._pack = pack
        self.limits: list[int] = []

    async def recall(
        self,
        *,
        candidate: object,
        query: str,
        limit: int,
    ) -> ContextPack:
        _ = candidate, query
        self.limits.append(limit)
        return self._pack


def _claim_payload() -> list[object]:
    claim = CanonicalClaim(
        subject="heterarchy-alexandria",
        predicate="uses",
        object="Obsidian",
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        polarity=MemoryClaimPolarity.POSITIVE,
    )
    return list(_CLAIMS_ADAPTER.dump_python((claim,), mode="json"))


def _context(context_id: str, *, with_claims: bool = True) -> ContextRecord:
    content = "heterarchy-alexandria uses Obsidian as canonical storage."
    metadata: dict[str, object] = {
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "relative_path": f"Contexts/{context_id}.md",
    }
    if with_claims:
        metadata["canonical_claims"] = _claim_payload()
    return ContextRecord(
        id=context_id,
        kind=ContextKind.MEMORY,
        title="Canonical storage decision",
        summary="Obsidian is canonical storage.",
        content=content,
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id=None,
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="Hermes",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=["memory", "storage"],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata=metadata,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def _pack(contexts: list[ContextRecord]) -> ContextPack:
    matches: list[ContextSearchMatch] = []
    for index, context in enumerate(contexts):
        chunk = ContextChunkRecord(
            id=f"chunk-{index}",
            context_id=context.id,
            chunk_index=0,
            heading="Decision",
            content=context.content,
            token_count=8,
            content_hash=f"chunk-hash-{index}",
            chunk_metadata={},
            created_at=NOW,
        )
        matches.append(
            ContextSearchMatch(
                context=context,
                chunk=chunk,
                score=1.0,
                fts_score=1.0,
                vector_score=1.0,
                why_retrieved="same canonical storage decision",
            )
        )
    return ContextPack(
        query="canonical storage",
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=[],
        recall_scopes=[ContextScope.PROJECT],
        matches=matches,
        context_pack="canonical storage contexts",
    )


def _service(
    *,
    contexts: list[ContextRecord],
    repository: SqlAlchemyMemoryReconciliationRepository,
) -> tuple[MemoryExistingReconciliationService, StaticContextService]:
    context_service = StaticContextService(contexts)
    recall_source = StaticRecallSource(_pack(contexts))
    return (
        MemoryExistingReconciliationService(
            context_service=context_service,
            candidate_service=MemoryCandidateService(),
            recall_service=MemoryCandidateRecallService(
                recall_source=recall_source,
                repository=repository,
            ),
            classifier=MemoryRelationClassifier(),
            plan_service=MemoryReconciliationPlanService(),
            repository=repository,
        ),
        context_service,
    )


def _request() -> ExistingMemoryReconciliationRequest:
    return ExistingMemoryReconciliationRequest(
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        max_contexts=10,
        batch_size=1,
        recall_limit=5,
    )


def test_existing_memory_preview_is_write_free(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                context = _context("obsidian:one", with_claims=False)
                service, context_service = _service(
                    contexts=[context],
                    repository=repository,
                )

                report = await service.preview(_request())

                assert report.dry_run is True
                assert report.scanned == 1
                assert report.temporal_backfill_candidates == 1
                assert report.temporal_states_written == 0
                assert report.plans_persisted == 0
                assert report.contexts_missing_claims == 1
                assert report.hard_delete_performed is False
                assert await repository.get_temporal_state(context.id) is None
                assert context_service.calls == [
                    (1, 0, "heterarchy-alexandria", ContextScope.PROJECT, False)
                ]
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_existing_memory_apply_backfills_recorded_at_without_inventing_validity(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                context = _context("obsidian:one", with_claims=False)
                service, _ = _service(contexts=[context], repository=repository)

                first = await service.apply(_request())
                second = await service.apply(_request())
                temporal = await repository.get_temporal_state(context.id)

                assert first.temporal_states_written == 1
                assert second.temporal_states_written == 0
                assert temporal is not None
                assert temporal.recorded_at == NOW
                assert temporal.observed_at is None
                assert temporal.valid_from is None
                assert temporal.valid_to is None
                assert temporal.is_current is True
                assert first.hard_delete_performed is False
                assert second.hard_delete_performed is False
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_existing_memory_apply_persists_only_reviewable_relation_plans_idempotently(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                contexts = [_context("obsidian:one"), _context("obsidian:two")]
                service, _ = _service(contexts=contexts, repository=repository)

                first = await service.apply(_request())
                second = await service.apply(_request())

                assert first.scanned == 2
                assert first.plans_generated == 2
                assert first.plans_persisted == 2
                assert second.plans_generated == 2
                assert second.plans_persisted == 0
                assert all(
                    item.primary_relation is MemoryRelationType.DUPLICATE
                    for item in first.assessments
                )
                assert all(item.plan_id is not None for item in first.assessments)
                assert all(item.plan_persisted for item in first.assessments)
                assert all(not item.plan_persisted for item in second.assessments)
                assert all(not item.requires_review for item in first.assessments)
        finally:
            await database.shutdown()

    anyio.run(scenario)
