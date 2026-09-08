"""Batch temporal view and future-validity regression evidence."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import anyio
from sqlalchemy import event
from tests.memory.reconciliation.test_memory_temporal_recall_service import (
    JULY_1,
    StaticContextService,
    _context,
    _match,
    _pack,
    _seed_temporal_states,
)

from app.memory.application.contexts.records.context_service_ports import (
    ContextTemporalSearchPort,
)
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.entities.memory_reconciliation import MemoryTemporalState
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.memory.domain.repositories.reconciliation.memory_reconciliation_temporal_repository import (
    IMemoryReconciliationTemporalRepository,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.infrastructure.database import Database

FUTURE = datetime(2026, 12, 1, tzinfo=UTC)


def test_apply_view_loads_temporal_states_with_one_batch_query() -> None:
    async def scenario() -> tuple[int, int]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                await _seed_temporal_states(repository)
                service = MemoryTemporalRecallService(
                    context_service=cast(
                        ContextTemporalSearchPort, StaticContextService(_pack())
                    ),
                    repository=repository,
                )

                async def run_view(
                    mode: MemoryTemporalRecallMode,
                    as_of: datetime | None = None,
                ) -> int:
                    statements = 0

                    def count_temporal_query(
                        _connection: object,
                        _cursor: object,
                        statement: str,
                        _parameters: object,
                        _context: object,
                        _executemany: bool,
                    ) -> None:
                        nonlocal statements
                        if "context_temporal_states" in statement:
                            statements += 1

                    event.listen(
                        database.engine.sync_engine,
                        "before_cursor_execute",
                        count_temporal_query,
                    )
                    try:
                        await service.apply_view(
                            _pack(),
                            MemoryTemporalRecallRequest(
                                query="storage decision",
                                mode=mode,
                                as_of=as_of,
                                limit=5,
                                project="heterarchy-alexandria",
                                include_scopes=(ContextScope.PROJECT,),
                            ),
                        )
                    finally:
                        event.remove(
                            database.engine.sync_engine,
                            "before_cursor_execute",
                            count_temporal_query,
                        )
                    return statements

                return (
                    await run_view(MemoryTemporalRecallMode.CURRENT),
                    await run_view(MemoryTemporalRecallMode.HISTORICAL, as_of=JULY_1),
                )
        finally:
            await database.shutdown()

    assert anyio.run(scenario) == (1, 1)


def test_current_view_excludes_future_valid_from_context() -> None:
    async def scenario() -> tuple[str, ...]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                future_id = "obsidian:future"
                await repository.upsert_temporal_state(
                    MemoryTemporalState(
                        context_id=future_id,
                        recorded_at=JULY_1,
                        observed_at=JULY_1,
                        valid_from=FUTURE,
                        valid_to=None,
                        is_current=True,
                    )
                )
                pack = _pack()
                future_context = _context(future_id, created_at=JULY_1)
                future_pack = replace(
                    pack,
                    matches=(*pack.matches, _match(future_context, 4)),
                )
                service = MemoryTemporalRecallService(
                    context_service=cast(
                        ContextTemporalSearchPort,
                        StaticContextService(future_pack),
                    ),
                    repository=repository,
                )
                result = await service.recall(
                    MemoryTemporalRecallRequest(
                        query="storage decision",
                        mode=MemoryTemporalRecallMode.CURRENT,
                        limit=10,
                    )
                )
                return tuple(item.match.context.id for item in result.matches)
        finally:
            await database.shutdown()

    assert "obsidian:future" not in anyio.run(scenario)


def test_empty_temporal_view_skips_repository_query() -> None:
    class EmptyRepository:
        calls = 0

        async def get_temporal_states(
            self,
            context_ids: tuple[str, ...],
        ) -> dict[str, MemoryTemporalState]:
            self.calls += 1
            assert context_ids == ()
            return {}

    async def scenario() -> int:
        repository = EmptyRepository()
        service = MemoryTemporalRecallService(
            context_service=cast(
                ContextTemporalSearchPort,
                StaticContextService(replace(_pack(), matches=())),
            ),
            repository=cast(IMemoryReconciliationTemporalRepository, repository),
        )
        await service.apply_view(
            replace(_pack(), matches=()),
            MemoryTemporalRecallRequest(
                query="empty",
                mode=MemoryTemporalRecallMode.CURRENT,
                limit=5,
            ),
        )
        return repository.calls

    assert anyio.run(scenario) == 0
