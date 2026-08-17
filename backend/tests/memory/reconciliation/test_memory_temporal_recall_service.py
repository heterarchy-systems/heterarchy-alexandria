"""Application tests for current and historical memory recall."""

from __future__ import annotations

import os

from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from app.memory.application.reconciliation.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
    temporal_state_from_context_metadata,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextPack,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import MemoryTemporalState
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.infrastructure.database import Database

JULY_1 = datetime(2026, 7, 1, tzinfo=UTC)
JULY_10 = datetime(2026, 7, 10, tzinfo=UTC)
JULY_20 = datetime(2026, 7, 20, tzinfo=UTC)
JULY_21 = datetime(2026, 7, 21, tzinfo=UTC)
JULY_25 = datetime(2026, 7, 25, tzinfo=UTC)


class StaticContextService:
    """Return one stable ranked Context pack for temporal filtering tests."""

    def __init__(self, pack: ContextPack) -> None:
        self.pack = pack
        self.calls: list[tuple[str, int]] = []

    async def search(
        self,
        *,
        query: str,
        strategy: RagStrategy,
        limit: int,
        project: str | None,
        kind: ContextKind | None,
        include_scopes: list[ContextScope] | None,
        workspace_id: str | None,
        agent_id: str | None,
        user_id: str | None,
        session_id: str | None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None,
    ) -> ContextPack:
        _ = (
            strategy,
            project,
            kind,
            include_scopes,
            workspace_id,
            agent_id,
            user_id,
            session_id,
            include_lifecycle_statuses,
        )
        self.calls.append((query, limit))
        return self.pack


def _context(
    context_id: str,
    *,
    created_at: datetime,
    metadata: dict[str, object] | None = None,
) -> ContextRecord:
    return ContextRecord(
        id=context_id,
        kind=ContextKind.MEMORY,
        title=context_id,
        summary=context_id,
        content=f"Memory content for {context_id}.",
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
        context_metadata={} if metadata is None else metadata,
        created_at=created_at,
        updated_at=created_at,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )


def _match(context: ContextRecord, index: int) -> ContextSearchMatch:
    return ContextSearchMatch(
        context=context,
        chunk=ContextChunkRecord(
            id=f"chunk-{index}",
            context_id=context.id,
            chunk_index=0,
            heading="Memory",
            content=context.content,
            token_count=5,
            content_hash=f"hash-{index}",
            chunk_metadata={},
            created_at=context.created_at,
        ),
        score=1.0 - index / 10,
        fts_score=1.0 - index / 10,
        vector_score=1.0 - index / 10,
        why_retrieved=f"rank-{index}",
    )


def _pack() -> ContextPack:
    contexts = [
        _context("obsidian:old", created_at=JULY_1),
        _context("obsidian:new", created_at=JULY_21),
        _context("obsidian:conflict", created_at=JULY_21),
    ]
    return ContextPack(
        query="storage decision",
        strategy=RagStrategy.HYBRID,
        effective_strategy=RagStrategy.HYBRID,
        warnings=[],
        recall_scopes=[ContextScope.PROJECT],
        matches=[_match(context, index) for index, context in enumerate(contexts)],
        context_pack="unfiltered",
    )


async def _seed_temporal_states(
    repository: SqlAlchemyMemoryReconciliationRepository,
) -> None:
    await repository.upsert_temporal_state(
        MemoryTemporalState(
            context_id="obsidian:old",
            recorded_at=JULY_1,
            observed_at=JULY_1,
            valid_from=JULY_1,
            valid_to=JULY_20,
            is_current=False,
            superseded_by=("obsidian:new",),
            relation_summary=("superseded_by:obsidian:new",),
        )
    )
    await repository.upsert_temporal_state(
        MemoryTemporalState(
            context_id="obsidian:new",
            recorded_at=JULY_21,
            observed_at=JULY_21,
            valid_from=JULY_21,
            valid_to=None,
            is_current=True,
            supersedes=("obsidian:old",),
            relation_summary=("supersedes:obsidian:old",),
        )
    )
    await repository.upsert_temporal_state(
        MemoryTemporalState(
            context_id="obsidian:conflict",
            recorded_at=JULY_21,
            observed_at=JULY_21,
            valid_from=JULY_21,
            valid_to=None,
            is_current=True,
            conflict_set_ids=("conflict-1",),
            relation_summary=("contradicts:obsidian:new",),
        )
    )


def test_temporal_recall_separates_current_historical_and_all_modes(
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
                await _seed_temporal_states(repository)
                context_service = StaticContextService(_pack())
                service = MemoryTemporalRecallService(
                    context_service=context_service,
                    repository=repository,
                )

                current = await service.recall(
                    MemoryTemporalRecallRequest(
                        query="storage decision",
                        mode=MemoryTemporalRecallMode.CURRENT,
                        limit=5,
                        project="heterarchy-alexandria",
                        include_scopes=(ContextScope.PROJECT,),
                    )
                )
                historical = await service.recall(
                    MemoryTemporalRecallRequest(
                        query="storage decision",
                        mode=MemoryTemporalRecallMode.HISTORICAL,
                        as_of=JULY_10,
                        limit=5,
                    )
                )
                all_states = await service.recall(
                    MemoryTemporalRecallRequest(
                        query="storage decision",
                        mode=MemoryTemporalRecallMode.ALL,
                        limit=5,
                    )
                )

                assert [item.match.context.id for item in current.matches] == [
                    "obsidian:new",
                    "obsidian:conflict",
                ]
                assert current.matches[0].supersedes == ("obsidian:old",)
                assert current.matches[1].conflict_set_ids == ("conflict-1",)
                assert "conflict-1" in current.warnings[-1]
                assert [item.match.context.id for item in historical.matches] == [
                    "obsidian:old"
                ]
                assert historical.as_of == JULY_10
                assert historical.matches[0].is_current is False
                assert [item.match.context.id for item in all_states.matches] == [
                    "obsidian:old",
                    "obsidian:new",
                    "obsidian:conflict",
                ]
                assert context_service.calls == [
                    ("storage decision", 15),
                    ("storage decision", 15),
                    ("storage decision", 5),
                ]
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_historical_recall_requires_explicit_aware_as_of(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                service = MemoryTemporalRecallService(
                    context_service=StaticContextService(_pack()),
                    repository=SqlAlchemyMemoryReconciliationRepository(session),
                )
                with pytest.raises(MemoryContextValidationError, match="as_of"):
                    await service.recall(
                        MemoryTemporalRecallRequest(
                            query="storage decision",
                            mode=MemoryTemporalRecallMode.HISTORICAL,
                        )
                    )
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_temporal_state_falls_back_to_canonical_frontmatter_metadata() -> None:
    context = _context(
        "obsidian:frontmatter",
        created_at=JULY_1,
        metadata={
            "recorded_at": JULY_25.isoformat(),
            "observed_at": JULY_21.isoformat(),
            "valid_from": JULY_21.isoformat(),
            "valid_to": None,
            "conflict_set_ids": ["conflict-frontmatter"],
            "supersedes_context_id": "old-frontmatter",
            "contradicts": [{"id": "other", "path": "Contexts/Other.md"}],
        },
    )

    state = temporal_state_from_context_metadata(context)

    assert state is not None
    assert state.recorded_at == JULY_25
    assert state.valid_from == JULY_21
    assert state.is_current is True
    assert state.conflict_set_ids == ("conflict-frontmatter",)
    assert state.supersedes == ("obsidian:old-frontmatter",)
    assert state.relation_summary == ("contradicts:obsidian:other",)
