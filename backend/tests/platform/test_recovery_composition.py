"""Contracts for request-scoped recovery callback composition."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import TypeAdapter

from app.container import create_recovery_callbacks
from app.memory.domain.entities.context_read_models import ContextReindexResult
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionOperationError,
    ObsidianGraphProjectionRebuildReport,
)
from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
    ObsidianGraphIssueDetail,
    ObsidianGraphIssueListQuery,
    ObsidianGraphIssueListResult,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionIssueCount,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphProjectionIssueCode,
)
from app.platform.config.memory_config import EmbeddingConfig


class _IntWithCustomFloat(int):
    def __float__(self) -> float:
        return 92.0


class _FloatWithCustomFloat(float):
    def __float__(self) -> float:
        return 93.0


class _RecordingDatabase:
    """Expose one active request session and its owning asyncio task."""

    def __init__(self) -> None:
        self.active = False
        self.task_id: int | None = None
        self.events: list[tuple[str, str | None, int]] = []

    def request_session(self) -> _RequestSession:
        return _RequestSession(self)

    def record(self, event: str, value: str | None = None) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.events.append((event, value, id(task)))


class _RequestSession:
    def __init__(self, database: _RecordingDatabase) -> None:
        self.database = database

    async def __aenter__(self) -> _RequestSession:
        assert not self.database.active
        task = asyncio.current_task()
        assert task is not None
        self.database.active = True
        self.database.task_id = id(task)
        self.database.record("enter")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.database.record("exit")
        self.database.active = False
        self.database.task_id = None


class _GraphService:
    def __init__(
        self,
        database: _RecordingDatabase,
        report: ObsidianGraphProjectionRebuildReport,
        failure: Literal["error", "cancel"] | None = None,
    ) -> None:
        self.database = database
        self.report = report
        self.failure = failure

    async def rebuild(self) -> ObsidianGraphProjectionRebuildReport:
        assert self.database.active
        assert self.database.task_id is not None
        self.database.record("graph_rebuild")
        if self.failure == "error":
            raise LookupError("graph rebuild failed")
        if self.failure == "cancel":
            raise asyncio.CancelledError
        return self.report


class _IssueService:
    def __init__(
        self, database: _RecordingDatabase, result: ObsidianGraphIssueListResult
    ) -> None:
        self.database = database
        self.result = result

    async def list_issues(
        self, query: ObsidianGraphIssueListQuery
    ) -> ObsidianGraphIssueListResult:
        assert query.limit == 50
        assert self.database.active
        self.database.record("issue_list")
        return self.result


class _EmbeddingOwner:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int, int]] = []

    async def recover(
        self,
        context: object,
        *,
        batch_observer: Callable[[ContextReindexResult], None],
    ) -> ContextReindexResult:
        self.calls.append((context, 250, 40))
        batch = ContextReindexResult(
            scanned=1,
            updated=0,
            skipped=1,
            warnings=("initial-warning",),
        )
        batch_observer(batch)
        batch.scanned = 2
        batch.updated = 1
        batch.warnings = ("batch-warning",)
        return ContextReindexResult(
            scanned=2,
            updated=1,
            skipped=1,
            warnings=("recovery-warning",),
        )


def _embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        _env_file=None,
        rag_vector_enabled=True,
        rag_embedding_provider="fastembed",
        rag_embedding_model="test/model",
        rag_embedding_dimensions=8,
        rag_embedding_cache_dir=None,
        rag_embedding_threads=1,
        rag_embedding_recovery_on_startup=False,
        rag_embedding_recovery_on_vault_reindex=False,
        rag_embedding_recovery_batch_size=250,
        rag_embedding_recovery_max_batches=40,
    )


def _graph_report() -> ObsidianGraphProjectionRebuildReport:
    return ObsidianGraphProjectionRebuildReport(
        status="failed",
        graph_read_model="postgresql",
        run_id="run-graph-1",
        scanned=8,
        indexed=6,
        updated=6,
        skipped=2,
        duration_seconds=0.125,
        issue_total=2,
        issue_counts=(
            ObsidianGraphProjectionIssueCount(
                code=ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE,
                count=2,
            ),
        ),
        issues=(
            ObsidianGraphProjectionOperationError(
                code="missing_target_note",
                relative_path="notes/source.md",
                note_id="note-source",
                edge_id="edge-1",
                detail="target is missing",
            ),
        ),
        issues_truncated=True,
        errors=(
            ObsidianGraphProjectionOperationError(
                code="source_build_failed",
                relative_path=None,
                note_id=None,
                edge_id=None,
                detail="reader unavailable",
            ),
        ),
    )


def _issue_result() -> ObsidianGraphIssueListResult:
    return ObsidianGraphIssueListResult(
        issues=(
            ObsidianGraphIssueDetail(
                issue_id="issue-1",
                code="missing_target_note",
                edge_id="edge-1",
                source_note_id="note-source",
                source_path="notes/source.md",
                source_title=None,
                target_path="notes/missing.md",
                relation="related_to",
                detail=None,
                projection_run_id="run-graph-1",
            ),
        ),
        next_cursor=None,
        run_id="run-graph-1",
    )


def _callbacks(
    database: _RecordingDatabase,
    *,
    embedding_owner: _EmbeddingOwner | None = None,
    graph_service: _GraphService | None = None,
    issue_service: _IssueService | None = None,
    compact_service: object | None = None,
    queue: object | None = None,
    dlq_service: object | None = None,
) -> object:
    async def graph_factory() -> _GraphService:
        assert graph_service is not None
        assert database.active
        database.record("graph_factory")
        return graph_service

    def issue_factory() -> _IssueService:
        assert issue_service is not None
        assert database.active
        database.record("issue_factory")
        return issue_service

    async def compact_factory() -> object:
        assert compact_service is not None
        assert database.active
        database.record("compact_factory")
        return compact_service

    return create_recovery_callbacks(
        config=_embedding_config(),
        database=database,
        embedding_owner=embedding_owner or _EmbeddingOwner(),
        graph_factory=graph_factory,
        links_factory=issue_factory,
        compact_factory=compact_factory,
        queue=queue,
        dlq_service=dlq_service,
    )


@pytest.mark.parametrize(
    "duration_seconds",
    [
        pytest.param(1.25, id="ordinary-float"),
        pytest.param(1, id="integer"),
        pytest.param(_IntWithCustomFloat(3), id="int-overrides-float"),
        pytest.param(_FloatWithCustomFloat(4.5), id="float-overrides-float"),
    ],
)
def test_graph_callbacks_match_complete_typed_json_and_keep_session_task_order(
    duration_seconds: float,
) -> None:
    async def scenario() -> None:
        database = _RecordingDatabase()
        graph_report = _graph_report()
        graph_report.duration_seconds = duration_seconds
        issue_result = _issue_result()
        callbacks = _callbacks(
            database,
            graph_service=_GraphService(database, graph_report),
            issue_service=_IssueService(database, issue_result),
        )
        assert database.events == []

        graph_payload = await callbacks.graph()
        expected_graph = TypeAdapter(ObsidianGraphProjectionRebuildReport).dump_python(
            graph_report, mode="json"
        )
        assert graph_payload == expected_graph
        assert type(graph_payload["duration_seconds"]) is float
        assert list(graph_payload) == list(expected_graph)
        assert await callbacks.links() == TypeAdapter(
            ObsidianGraphIssueListResult
        ).dump_python(issue_result, mode="json")

        event_names = [event for event, _, _ in database.events]
        assert event_names == [
            "enter",
            "graph_factory",
            "graph_rebuild",
            "exit",
            "enter",
            "issue_factory",
            "issue_list",
            "exit",
        ]
        assert len({task_id for _, _, task_id in database.events}) == 1
        assert not database.active

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("failure", "exception_type"),
    [("error", LookupError), ("cancel", asyncio.CancelledError)],
)
def test_graph_callback_exits_request_session_after_error_or_cancellation(
    failure: Literal["error", "cancel"],
    exception_type: type[BaseException],
) -> None:
    async def scenario() -> None:
        database = _RecordingDatabase()
        callbacks = _callbacks(
            database,
            graph_service=_GraphService(database, _graph_report(), failure=failure),
        )
        with pytest.raises(exception_type):
            await callbacks.graph()
        assert [event for event, _, _ in database.events] == [
            "enter",
            "graph_factory",
            "graph_rebuild",
            "exit",
        ]
        assert len({task_id for _, _, task_id in database.events}) == 1
        assert not database.active

    asyncio.run(scenario())


def test_embedding_current_and_disabled_dlq_callbacks_preserve_payloads() -> None:
    async def scenario() -> None:
        database = _RecordingDatabase()
        embedding_owner = _EmbeddingOwner()
        compact = SimpleNamespace(id="compact-1", status=MemoryCompactStatus.CURRENT)

        async def current() -> SimpleNamespace:
            return compact

        callbacks = _callbacks(
            database,
            embedding_owner=embedding_owner,
            compact_service=SimpleNamespace(current=current),
        )
        context = object()

        with pytest.raises(ValueError, match="bounds differ"):
            await callbacks.embedding(context, batch_size=10, max_batches=40)
        assert embedding_owner.calls == []

        assert await callbacks.embedding(
            context,
            batch_size=250,
            max_batches=40,
        ) == {
            "scanned": 2,
            "updated": 1,
            "skipped": 1,
            "warnings": ["recovery-warning"],
            "batches": [
                {
                    "scanned": 2,
                    "updated": 1,
                    "skipped": 1,
                    "warnings": ["batch-warning"],
                }
            ],
            "batch_size": 250,
            "max_batches": 40,
        }
        assert embedding_owner.calls == [(context, 250, 40)]
        assert await callbacks.current() == {
            "project": None,
            "available": True,
            "compact_id": "compact-1",
            "status": "CURRENT",
            "scope": "default_project",
        }
        assert await callbacks.dlq() == {
            "enabled": False,
            "ready": True,
            "entries": [],
            "truncated": False,
        }
        assert [event for event, _, _ in database.events] == [
            "enter",
            "compact_factory",
            "exit",
        ]
        assert len({task_id for _, _, task_id in database.events}) == 1
        assert not database.active

    asyncio.run(scenario())
