"""Application tests for explicit memory conflict lifecycle management."""

from __future__ import annotations

import os

from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from app.memory.application.reconciliation.memory_conflict_service import (
    MemoryConflictService,
)
from app.memory.domain.entities.memory_reconciliation import MemoryConflictSet
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import MemoryConflictStatus
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.infrastructure.database import Database

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _conflict() -> MemoryConflictSet:
    return MemoryConflictSet(
        conflict_set_id="conflict-service",
        context_ids=("obsidian:new", "obsidian:old"),
        candidate_id="candidate-service",
        subject_key="heterarchy-alexandria",
        claim_key="heterarchy-alexandria|uses",
        scope=ContextScope.PROJECT,
        validity_overlap=True,
        reason="Conflicting active claims",
        status=MemoryConflictStatus.OPEN,
        resolution=None,
        created_at=NOW,
        resolved_at=None,
    )


def test_conflict_service_lists_reviews_and_resolves_preserving_contexts(
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
                await repository.upsert_conflict(_conflict())
                service = MemoryConflictService(repository)

                assert await service.list(status=MemoryConflictStatus.OPEN) == [
                    _conflict()
                ]
                reviewing = await service.mark_reviewing("conflict-service")
                resolved = await service.resolve(
                    "conflict-service",
                    status=MemoryConflictStatus.RESOLVED_KEEP_BOTH,
                    resolution="Both memories remain historically valid.",
                )

                assert reviewing.status is MemoryConflictStatus.REVIEWING
                assert resolved.status is MemoryConflictStatus.RESOLVED_KEEP_BOTH
                assert resolved.resolution == "Both memories remain historically valid."
                assert resolved.resolved_at is not None
                assert resolved.context_ids == ("obsidian:new", "obsidian:old")
                assert await service.list(status=MemoryConflictStatus.OPEN) == []
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_conflict_service_rejects_invalid_resolution_and_missing_conflict(
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
                service = MemoryConflictService(repository)
                with pytest.raises(MemoryContextNotFoundError):
                    await service.get("missing")
                with pytest.raises(MemoryContextValidationError):
                    await service.list(limit=0)
                await repository.upsert_conflict(_conflict())
                with pytest.raises(MemoryContextValidationError):
                    await service.resolve(
                        "conflict-service",
                        status=MemoryConflictStatus.OPEN,
                        resolution="Not a final state",
                    )
        finally:
            await database.shutdown()

    anyio.run(scenario)
