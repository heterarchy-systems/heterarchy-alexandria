"""Optional Neo4j graph projection adapter contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

import anyio
import pytest
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionIssueCode,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionNode,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.infrastructure.graph import neo4j_graph_projection_factory
from app.obsidian.infrastructure.graph.neo4j_graph_projection_factory import (
    optional_neo4j_graph_projection_repository,
)
from app.obsidian.infrastructure.graph.neo4j_graph_projection_queries import (
    ACTIVATE_PROJECTION_METADATA,
    CREATE_NOTE_KEY_CONSTRAINT,
    CREATE_PROJECTION_NAME_CONSTRAINT,
    DELETE_PROJECTION_RUN_NODES,
    READ_CONTEXT_EVIDENCE,
    READ_EDGES,
    READ_NODES,
    READ_PROJECTION_METADATA,
    READ_RELATED_NOTES,
    UPSERT_EDGES,
    UPSERT_NODES,
)
from app.obsidian.infrastructure.graph.neo4j_obsidian_graph_projection_repository import (
    Neo4jObsidianGraphProjectionRepository,
    Neo4jProjectionDriver,
)
from app.platform.config.app_config import AppConfig


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self._rows = rows or []
        self.consumed = False

    async def data(self) -> list[dict[str, object]]:
        return self._rows

    async def consume(self) -> object:
        self.consumed = True
        return object()


class _FakeTransaction:
    def __init__(self, reads: dict[str, list[dict[str, object]]]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.results: list[_FakeResult] = []
        self._reads = reads

    async def run(self, query: str, **parameters: object) -> _FakeResult:
        self.calls.append((query, parameters))
        result = _FakeResult(self._reads.get(query))
        self.results.append(result)
        return result


TransactionCallback = Callable[..., Awaitable[object]]


class _FakeSession:
    def __init__(self, tx: _FakeTransaction) -> None:
        self.tx = tx
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> _FakeSession:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.exited = True

    async def execute_write(
        self,
        callback: TransactionCallback,
        *args: object,
        **kwargs: object,
    ) -> object:
        return await callback(self.tx, *args, **kwargs)

    async def execute_read(
        self,
        callback: TransactionCallback,
        *args: object,
        **kwargs: object,
    ) -> object:
        return await callback(self.tx, *args, **kwargs)


class _FakeDriver:
    def __init__(self, reads: dict[str, list[dict[str, object]]] | None = None) -> None:
        self._reads = reads or {}
        self.sessions: list[tuple[str, _FakeSession]] = []
        self.closed = False
        self.connectivity_verified = False

    def session(self, *, database: str) -> _FakeSession:
        session = _FakeSession(_FakeTransaction(self._reads))
        self.sessions.append((database, session))
        return session

    async def close(self) -> None:
        self.closed = True

    async def verify_connectivity(self) -> None:
        self.connectivity_verified = True


def _projection() -> ObsidianGraphProjection:
    return ObsidianGraphProjection(
        nodes=(
            ObsidianGraphProjectionNode(
                note_id="note-a",
                relative_path="Alexandria/Contexts/note-a.md",
                alexandria_type=AlexandriaNoteType.CONTEXT,
                title="Note A",
                status="active",
                project="heterarchy-alexandria",
            ),
        ),
        edges=(
            ObsidianGraphProjectionEdge(
                edge_id="edge-a-missing",
                source_note_id="note-a",
                source_path="Alexandria/Contexts/note-a.md",
                target_note_id=None,
                target_path="Alexandria/Contexts/missing.md",
                relation=ObsidianRelationType.RELATED,
                confidence=0.8,
                source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
            ),
        ),
    )


def test_disabled_factory_does_not_create_neo4j_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default backend mode should not create a Neo4j runtime driver."""
    config = AppConfig(_env_file=None, graph_read_model="disabled")

    def fail_driver(
        _uri: str,
        *,
        auth: tuple[str, str],
    ) -> object:
        _ = auth
        raise AssertionError("disabled mode created the Neo4j driver")

    monkeypatch.setattr(
        neo4j_graph_projection_factory.AsyncGraphDatabase,
        "driver",
        staticmethod(fail_driver),
    )

    async def scenario() -> object:
        async with optional_neo4j_graph_projection_repository(config=config) as repo:
            return repo

    assert anyio.run(scenario) is None


def test_neo4j_queries_use_named_constraints_unwind_and_idempotent_merge() -> None:
    """Cypher templates should encode stable, parameterized projection writes."""
    assert "CREATE CONSTRAINT obsidian_graph_note_projection_key" in (
        CREATE_NOTE_KEY_CONSTRAINT
    )
    assert "CREATE CONSTRAINT obsidian_graph_projection_name" in (
        CREATE_PROJECTION_NAME_CONSTRAINT
    )
    assert "IF NOT EXISTS" in CREATE_NOTE_KEY_CONSTRAINT
    assert "UNWIND $nodes AS row" in UPSERT_NODES
    assert "MERGE" in UPSERT_NODES
    assert "UNWIND $edges AS row" in UPSERT_EDGES
    assert "MERGE" in UPSERT_EDGES
    assert "projection_run_id: $run_id" in READ_NODES
    assert "$run_id" in DELETE_PROJECTION_RUN_NODES
    assert "previous_run_id" in ACTIVATE_PROJECTION_METADATA


def test_adapter_uses_one_short_lived_session_per_operation_and_awaits_close() -> None:
    """Driver lifetime is shared while each repository call owns one session."""
    driver = _FakeDriver()
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=cast(Neo4jProjectionDriver, driver),
        database="neo4j",
    )

    async def scenario() -> None:
        await repository.verify_connectivity()
        await repository.start_rebuild(run_id="run-test", projection_version=1)
        await repository.write_rebuild_batch(
            run_id="run-test", projection_version=1, batch=_projection()
        )
        await repository.complete_rebuild(
            run_id="run-test",
            projection_version=1,
            issue_counts=(
                ObsidianGraphProjectionIssueCount(
                    code=ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE,
                    count=12,
                ),
            ),
        )
        await repository.close()

    anyio.run(scenario)

    assert driver.connectivity_verified is True
    assert driver.closed is True
    assert len(driver.sessions) == 3
    assert all(database == "neo4j" for database, _ in driver.sessions)
    assert all(session.entered and session.exited for _, session in driver.sessions)
    assert driver.sessions[0][1] is not driver.sessions[1][1]
    assert all(
        result.consumed
        for _, session in driver.sessions
        for result in session.tx.results
    )


def test_adapter_writes_projection_metadata_without_null_merge_identifiers() -> None:
    """Write parameters should carry run/version metadata and stable target keys."""
    driver = _FakeDriver()
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=cast(Neo4jProjectionDriver, driver),
        database="neo4j",
    )

    async def scenario() -> None:
        await repository.write_rebuild_batch(
            run_id="run-test", projection_version=1, batch=_projection()
        )
        await repository.complete_rebuild(
            run_id="run-test",
            projection_version=1,
            issue_counts=(
                ObsidianGraphProjectionIssueCount(
                    code=ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE,
                    count=12,
                ),
            ),
        )

    anyio.run(scenario)

    calls = driver.sessions[0][1].tx.calls
    edge_parameters = next(
        parameters for query, parameters in calls if query == UPSERT_EDGES
    )
    edge = cast(list[dict[str, object]], edge_parameters["edges"])[0]
    assert edge["target_key"] == "run-test:path:Alexandria/Contexts/missing.md"
    assert edge["target_note_id"] is None
    assert edge_parameters["run_id"] == "run-test"
    assert edge_parameters["projection_version"] == 1
    activation_parameters = next(
        parameters
        for query, parameters in driver.sessions[1][1].tx.calls
        if query == ACTIVATE_PROJECTION_METADATA
    )
    assert activation_parameters["run_id"] == "run-test"
    assert activation_parameters["issue_total"] == 12
    assert activation_parameters["issue_counts_json"] == '{"missing_target_note":12}'
    assert all("password" not in parameters for _, parameters in calls)


def test_adapter_snapshot_maps_typed_nodes_and_edges_in_stable_order() -> None:
    """Neo4j transport rows should not escape the repository boundary."""
    driver = _FakeDriver(
        reads={
            READ_PROJECTION_METADATA: [
                {
                    "run_id": "run-active",
                    "projection_version": 1,
                    "issue_total": 12,
                    "issue_counts_json": '{"missing_target_note":12}',
                }
            ],
            READ_NODES: [
                {
                    "note_id": "note-a",
                    "relative_path": "Alexandria/Contexts/note-a.md",
                    "alexandria_type": "context",
                    "title": "Note A",
                    "status": "active",
                    "project": "heterarchy-alexandria",
                }
            ],
            READ_EDGES: [
                {
                    "edge_id": "edge-a-missing",
                    "source_note_id": "note-a",
                    "source_path": "Alexandria/Contexts/note-a.md",
                    "target_note_id": None,
                    "target_path": "Alexandria/Contexts/missing.md",
                    "relation": "related",
                    "confidence": 0.8,
                    "source_kind": "frontmatter",
                }
            ],
        }
    )
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=cast(Neo4jProjectionDriver, driver),
        database="neo4j",
    )

    state = anyio.run(repository.state)
    snapshot = state.projection

    assert state.initialized is True
    assert state.run_id == "run-active"
    assert state.projection_version == 1
    assert state.issue_total == 12
    assert [(item.code, item.count) for item in state.issue_counts] == [
        (ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE, 12)
    ]
    assert tuple(node.note_id for node in snapshot.nodes) == ("note-a",)
    assert snapshot.nodes[0].alexandria_type is AlexandriaNoteType.CONTEXT
    assert tuple(edge.edge_id for edge in snapshot.edges) == ("edge-a-missing",)
    assert snapshot.edges[0].target_note_id is None


def test_adapter_reports_uninitialized_when_projection_metadata_is_absent() -> None:
    """An empty database is never-built, not a successful empty projection."""
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=cast(Neo4jProjectionDriver, _FakeDriver()),
        database="neo4j",
    )

    state = anyio.run(repository.state)

    assert state.initialized is False
    assert state.run_id is None
    assert state.projection == ObsidianGraphProjection()


def test_adapter_reads_related_notes_from_active_run_with_bound_parameters() -> None:
    driver = _FakeDriver(
        reads={
            READ_RELATED_NOTES: [
                {
                    "related_note_id": "note-b",
                    "edge_id": "edge-a-b",
                    "relation": "derived_from",
                    "source_kind": "frontmatter",
                    "direction": "outgoing",
                    "score": 1.9,
                }
            ]
        }
    )
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=cast(Neo4jProjectionDriver, driver),
        database="neo4j",
    )

    async def scenario() -> tuple[ObsidianGraphRelatedNote, ...]:
        return await repository.related_notes(note_id="note-a", limit=7)

    related = anyio.run(scenario)

    assert related[0].note_id == "note-b"
    assert related[0].direction == "outgoing"
    query, parameters = driver.sessions[0][1].tx.calls[0]
    assert query == READ_RELATED_NOTES
    assert parameters == {
        "projection_name": "obsidian",
        "note_id": "note-a",
        "limit": 7,
    }
    assert driver.sessions[0][1].tx.results[0].consumed is True


def test_adapter_limits_context_evidence_to_recalled_ids() -> None:
    driver = _FakeDriver(
        reads={
            READ_CONTEXT_EVIDENCE: [
                {
                    "edge_id": "edge-a-b",
                    "source_note_id": "note-a",
                    "target_note_id": "note-b",
                    "target_title": "Note B",
                    "signal": "graph_proximity",
                    "relation": "related",
                }
            ]
        }
    )
    repository = Neo4jObsidianGraphProjectionRepository(
        driver=cast(Neo4jProjectionDriver, driver),
        database="neo4j",
    )

    async def scenario() -> tuple[ObsidianGraphContextEvidence, ...]:
        return await repository.context_evidence(note_ids=("note-a", "note-b"))

    evidence = anyio.run(scenario)

    assert evidence[0].target_title == "Note B"
    assert evidence[0].signal == "graph_proximity"
    query, parameters = driver.sessions[0][1].tx.calls[0]
    assert query == READ_CONTEXT_EVIDENCE
    assert parameters["note_ids"] == ["note-a", "note-b"]
    assert "$note_ids" in query
