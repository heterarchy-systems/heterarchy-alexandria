"""Application tests for memory reconciliation candidate and preview planning."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from pydantic import TypeAdapter

from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.candidates.memory_evolution_candidate_evidence_service import (
    MemoryEvolutionCandidateEvidenceService,
)
from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_preview_service import (
    MemoryReconciliationPreviewService,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryCandidateCreate,
    MemoryReconciliationPreviewRequest,
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
    MemoryReconciliationActionType,
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.memory.domain.repositories.contexts.memory_candidate_recall_source import (
    IMemoryCandidateRecallSource,
)
from app.memory.infrastructure.providers.native_memory_reconciliation_candidate_compute_provider import (
    create_native_memory_reconciliation_candidate_compute_provider,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.infrastructure.database import Database

NOW = datetime(2026, 7, 25, tzinfo=UTC)
_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])


class StaticRecallSource(IMemoryCandidateRecallSource):
    """Return one prebuilt Context pack for application planning tests."""

    def __init__(self, pack: ContextPack) -> None:
        self._pack = pack
        self.queries: list[str] = []

    async def recall(
        self,
        *,
        candidate: object,
        query: str,
        limit: int,
    ) -> ContextPack:
        _ = candidate, limit
        self.queries.append(query)
        return self._pack


def _claim(
    *,
    object_value: str,
    polarity: MemoryClaimPolarity = MemoryClaimPolarity.POSITIVE,
) -> CanonicalClaim:
    return CanonicalClaim(
        subject="heterarchy-alexandria",
        predicate="uses",
        object=object_value,
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        polarity=polarity,
    )


def _request(
    *,
    object_value: str = "Redis",
    polarity: MemoryClaimPolarity = MemoryClaimPolarity.POSITIVE,
    idempotency_key: str | None = None,
) -> MemoryReconciliationPreviewRequest:
    return MemoryReconciliationPreviewRequest(
        candidate=MemoryCandidateCreate(
            candidate_id="candidate-1",
            title="Current storage decision",
            body=f"heterarchy-alexandria uses {object_value}.",
            scope=ContextScope.PROJECT,
            project="heterarchy-alexandria",
            canonical_claims=(_claim(object_value=object_value, polarity=polarity),),
            tags=("memory", "memory", " decision "),
            recorded_at=NOW,
        ),
        idempotency_key=idempotency_key,
    )


def _empty_pack() -> ContextPack:
    return ContextPack(
        query="",
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=[],
        recall_scopes=[ContextScope.PROJECT],
        matches=[],
        context_pack="",
    )


def _conflicting_pack() -> ContextPack:
    claim_payload = _CLAIMS_ADAPTER.dump_python(
        (_claim(object_value="Redis"),),
        mode="json",
    )
    context = ContextRecord(
        id="obsidian:context-existing",
        kind=ContextKind.MEMORY,
        title="Existing storage decision",
        summary="The current storage decision.",
        content="heterarchy-alexandria uses Redis.",
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
        tags=["memory"],
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=[],
        restore_prompt=None,
        context_metadata={
            "canonical_claims": claim_payload,
            "content_hash": "existing-hash",
            "relative_path": "Contexts/existing.md",
        },
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id="chunk-1",
        context_id=context.id,
        chunk_index=0,
        heading="Decision",
        content=context.content,
        token_count=5,
        content_hash="chunk-hash",
        chunk_metadata={},
        created_at=NOW,
    )
    return ContextPack(
        query="heterarchy-alexandria uses Redis",
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=[],
        recall_scopes=[ContextScope.PROJECT],
        matches=[
            ContextSearchMatch(
                context=context,
                chunk=chunk,
                score=1.0,
                fts_score=1.0,
                vector_score=1.0,
                why_retrieved="canonical claim match",
            )
        ],
        context_pack="existing context",
    )


def _preview_service(
    *,
    recall_source: StaticRecallSource,
    repository: SqlAlchemyMemoryReconciliationRepository,
) -> MemoryReconciliationPreviewService:
    return MemoryReconciliationPreviewService(
        candidate_service=MemoryCandidateService(),
        recall_service=MemoryCandidateRecallService(
            recall_source=recall_source,
            repository=repository,
        ),
        candidate_evidence_service=MemoryEvolutionCandidateEvidenceService(
            create_native_memory_reconciliation_candidate_compute_provider()
        ),
        classifier=MemoryRelationClassifier(),
        plan_service=MemoryReconciliationPlanService(),
        repository=repository,
    )


def test_candidate_service_normalizes_identity_tags_and_hash() -> None:
    candidate = MemoryCandidateService().create(_request().candidate)

    assert candidate.project == "heterarchy-alexandria"
    assert candidate.tags == ("memory", "decision")
    assert len(candidate.content_hash) == 64
    assert candidate.canonical_claims[0].project == "heterarchy-alexandria"


def test_candidate_service_rejects_missing_scope_identity_and_invalid_interval() -> (
    None
):
    service = MemoryCandidateService()
    with pytest.raises(MemoryContextValidationError, match="MISSING_PROJECT"):
        service.create(
            MemoryCandidateCreate(
                title="Invalid",
                body="Missing project identity.",
                scope=ContextScope.PROJECT,
            )
        )
    with pytest.raises(MemoryContextValidationError, match="valid_to"):
        service.create(
            MemoryCandidateCreate(
                title="Invalid",
                body="Invalid interval.",
                scope=ContextScope.GLOBAL,
                valid_from=NOW,
                valid_to=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )


def test_preview_without_matches_creates_unrelated_context_plan(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                source = StaticRecallSource(_empty_pack())
                plan = await _preview_service(
                    recall_source=source,
                    repository=repository,
                ).preview(_request())
                await session.commit()

                assert plan.primary_decision is MemoryRelationType.UNRELATED
                assert plan.status is MemoryReconciliationStatus.PLANNED
                assert [action.action_type for action in plan.actions] == [
                    MemoryReconciliationActionType.CREATE_CONTEXT
                ]
                assert "No existing Context candidate was recalled." in plan.warnings
                assert plan.candidate_evidence is not None
                assert plan.candidate_evidence.compute_authority == (
                    "rust:reconciliation_candidates:v1"
                )
                assert plan.candidate_evidence.compared_context_ids == ()
                assert plan.candidate_evidence.metrics.input_items == 1
                assert await repository.get_plan(plan.plan_id) == plan
                assert source.queries == ["heterarchy-alexandria uses Redis"]
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_contradiction_preview_is_review_required_and_idempotent(
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
                source = StaticRecallSource(_conflicting_pack())
                service = _preview_service(
                    recall_source=source,
                    repository=repository,
                )
                request = _request(
                    object_value="PostgreSQL",
                    idempotency_key="preview-conflict-1",
                )
                first = await service.preview(request)
                second = await service.preview(request)
                await session.commit()

                assert first.plan_id == second.plan_id
                assert first.primary_decision is MemoryRelationType.CONTRADICTS
                assert first.status is MemoryReconciliationStatus.REVIEW_REQUIRED
                assert first.requires_review is True
                assert first.conflicting_context_ids == ("obsidian:context-existing",)
                assert {action.action_type for action in first.actions} == {
                    MemoryReconciliationActionType.CREATE_CONTEXT,
                    MemoryReconciliationActionType.CREATE_RELATION,
                    MemoryReconciliationActionType.CREATE_CONFLICT_SET,
                    MemoryReconciliationActionType.QUEUE_REVIEW,
                }
                assert len(source.queries) == 1
        finally:
            await database.shutdown()

    anyio.run(scenario)
