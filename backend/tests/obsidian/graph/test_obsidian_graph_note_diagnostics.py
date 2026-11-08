"""Per-note graph diagnostics from the rebuildable Obsidian index."""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from tests.config_test_data import application_container

from app.main import app as default_app, create_app
from app.obsidian.application.graph.diagnostics import (
    obsidian_graph_note_diagnostics_service as graph_note_diagnostics_module,
)
from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianEdge, ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianIndexStatus,
    ObsidianRelationType,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianEdgeORM,
    ObsidianFileORM,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.common_exceptions import IndexMaintenanceConflictError
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models
_NOW = datetime(2026, 8, 3, tzinfo=UTC)
_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


def _note(
    note_id: str,
    path: str,
    *,
    title: str | None = None,
    aliases: list[str] | None = None,
    index_status: ObsidianIndexStatus = ObsidianIndexStatus.INDEXED,
) -> ObsidianNote:
    return ObsidianNote(
        note_id=note_id,
        relative_path=path,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=title or note_id,
        status="active",
        tags=(),
        project="heterarchy-alexandria",
        source="test",
        content_hash=f"hash-{note_id}",
        frontmatter={} if aliases is None else {"aliases": aliases},
        body=f"# {title or note_id}",
        index_status=index_status,
        error_message=(
            "frontmatter validation failed"
            if index_status is ObsidianIndexStatus.ERROR
            else None
        ),
        size_bytes=10,
        modified_at=_NOW,
        indexed_at=_NOW,
    )


def _edge(
    edge_id: str,
    *,
    source_note_id: str = "source",
    target_note_id: str | None = None,
    target_path: str,
) -> ObsidianEdge:
    return ObsidianEdge(
        edge_id=edge_id,
        source_note_id=source_note_id,
        source_path="Alexandria/Source.md",
        target_note_id=target_note_id,
        target_path=target_path,
        relation=ObsidianRelationType.RELATED,
        confidence=0.8,
        source_kind=ObsidianEdgeSourceKind.WIKILINK,
        created_at=_NOW,
        indexed_at=_NOW,
    )


class _Repository:
    def __init__(self, notes: tuple[ObsidianNote, ...]) -> None:
        self._by_id = {note.note_id: note for note in notes}
        self._by_path = {note.relative_path: note for note in notes}

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        return self._by_id.get(note_id)

    async def get_by_path(self, relative_path: str) -> ObsidianNote | None:
        return self._by_path.get(relative_path)


class _LookupObservingRepository(_Repository):
    def __init__(self, notes: tuple[ObsidianNote, ...]) -> None:
        super().__init__(notes)
        self.lookups = 0

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        self.lookups += 1
        return await super().get_by_id(note_id)

    async def get_by_path(self, relative_path: str) -> ObsidianNote | None:
        self.lookups += 1
        return await super().get_by_path(relative_path)


class _Source:
    def __init__(
        self,
        notes: tuple[ObsidianNote, ...],
        edges: tuple[ObsidianEdge, ...],
    ) -> None:
        self._notes = notes
        self._edges = edges

    async def list_projection_notes(self) -> tuple[ObsidianNote, ...]:
        return self._notes

    async def list_projection_edges(self) -> tuple[ObsidianEdge, ...]:
        return self._edges


class _ProjectionStatusService:
    async def status(self) -> ObsidianGraphProjectionStatusReport:
        return ObsidianGraphProjectionStatusReport(
            status="ready",
            graph_read_model="postgresql",
            enabled=True,
            node_count=0,
            edge_count=0,
            errors=(),
        )


async def _validate_fixture() -> object:
    notes = (
        _note("source", "Alexandria/Source.md", title="Source"),
        _note("resolved", "Alexandria/Resolved.md", title="Resolved"),
        _note("alias-target", "Alexandria/AliasTarget.md", aliases=["Alias Link"]),
        _note("ambiguous-a", "Alexandria/FolderA/Repeated.md"),
        _note("ambiguous-b", "Alexandria/FolderB/Repeated.md"),
        _note(
            "stale-target",
            "Alexandria/Stale.md",
            index_status=ObsidianIndexStatus.STALE,
        ),
    )
    edges = (
        _edge("edge-1", target_note_id="resolved", target_path="old/path.md"),
        _edge("edge-2", target_path="Alexandria/Nope.md"),
        _edge("edge-3", target_path="Alexandria/Repeated.md"),
        _edge(
            "edge-4", target_note_id="stale-target", target_path="Alexandria/Stale.md"
        ),
        _edge("edge-5", target_path="Alias Link.md"),
        _edge("edge-other", source_note_id="other", target_path="Alexandria/Nope.md"),
    )
    service = ObsidianGraphNoteDiagnosticsService(
        repository=_Repository(notes),
        source=_Source(notes, edges),
        projection_service=_ProjectionStatusService(),
    )
    return await service.validate_note_links(
        note_id="source",
        include_resolved_targets=True,
    )


def test_validate_note_links_reports_outgoing_resolution_details() -> None:
    """Diagnostics should count parsed, resolved, and explicit unresolved edges."""
    report = anyio.run(_validate_fixture)

    assert report.note.exists is True
    assert report.note.note_id == "source"
    assert report.note.index_status == "indexed"
    assert report.outgoing.parsed_count == 5
    assert report.outgoing.resolved_count == 2
    assert report.outgoing.unresolved_count == 3
    assert tuple(target.edge_id for target in report.outgoing.resolved_targets) == (
        "edge-1",
        "edge-5",
    )
    unresolved = {
        target.edge_id: target for target in report.outgoing.unresolved_targets
    }
    assert unresolved["edge-2"].code == "missing_target_note"
    assert unresolved["edge-3"].code == "ambiguous_target_note"
    assert unresolved["edge-3"].candidate_note_ids == (
        "ambiguous-a",
        "ambiguous-b",
    )
    assert unresolved["edge-4"].code == "target_not_indexed"
    assert unresolved["edge-4"].candidate_paths == ("Alexandria/Stale.md",)
    assert report.projection_status.status == "ready"


def test_validate_note_links_reports_missing_note_without_error() -> None:
    """Missing selectors should still return an existence diagnostic."""

    async def scenario() -> object:
        service = ObsidianGraphNoteDiagnosticsService(
            repository=_Repository(()),
            source=_Source((), ()),
            projection_service=_ProjectionStatusService(),
        )
        return await service.validate_note_links(path="Alexandria/Missing.md")

    report = anyio.run(scenario)

    assert report.selector.path == "Alexandria/Missing.md"
    assert report.note.exists is False
    assert report.outgoing.parsed_count == 0


def test_validate_note_links_does_not_mask_missing_explicit_id_with_path() -> None:
    """A path candidate is evidence, not a substitute for a broken target id."""

    async def scenario() -> object:
        notes = (
            _note("source", "Alexandria/Source.md"),
            _note("path-peer", "Alexandria/Target.md"),
        )
        edge = _edge(
            "broken-explicit-id",
            target_note_id="missing-id",
            target_path="Alexandria/Target.md",
        )
        service = ObsidianGraphNoteDiagnosticsService(
            repository=_Repository(notes),
            source=_Source(notes, (edge,)),
            projection_service=_ProjectionStatusService(),
        )
        return await service.validate_note_links(note_id="source")

    report = anyio.run(scenario)

    assert report.outgoing.resolved_count == 0
    assert report.outgoing.unresolved_count == 1
    unresolved = report.outgoing.unresolved_targets[0]
    assert unresolved.code == "missing_target_note"
    assert unresolved.candidate_note_ids == ("path-peer",)
    assert unresolved.candidate_paths == ("Alexandria/Target.md",)


def test_rebuild_note_graph_fails_fast_before_target_read_or_canonical_parse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An active lease must reject a note rebuild before it reads its target."""
    repository = _LookupObservingRepository((_note("source", "Alexandria/Source.md"),))
    coordinator = IndexMaintenanceCoordinator()
    store = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    parse_calls: list[Path] = []

    def observe_parse(
        path: Path,
        relative_path: str,
        alexandria_root: str,
        max_source_bytes: int | None = None,
    ) -> None:
        parse_calls.append(path)
        return None

    monkeypatch.setattr(
        graph_note_diagnostics_module,
        "note_index_from_path",
        observe_parse,
    )
    service = ObsidianGraphNoteDiagnosticsService(
        repository=repository,
        source=_Source((), ()),
        projection_service=_ProjectionStatusService(),
        vault_config_store=store,
        index_maintenance_coordinator=coordinator,
    )

    async def scenario() -> None:
        lease_acquired = anyio.Event()
        release_lease = anyio.Event()

        async def hold_lease() -> None:
            async with coordinator.operation("other_graph_maintenance"):
                lease_acquired.set()
                await release_lease.wait()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(hold_lease)
            await lease_acquired.wait()
            try:
                with pytest.raises(IndexMaintenanceConflictError):
                    await service.rebuild_note_graph(note_id="source")
            finally:
                release_lease.set()

    anyio.run(scenario)

    assert repository.lookups == 0
    assert parse_calls == []


def test_rebuild_keeps_lease_until_blocking_parse_finishes_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancellation must not detach the parse worker from its maintenance lease."""
    repository = _LookupObservingRepository((_note("source", "Alexandria/Source.md"),))
    coordinator = IndexMaintenanceCoordinator()
    store = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    parse_started = threading.Event()
    release_parse = threading.Event()
    parse_finished = threading.Event()
    parse_arguments: list[tuple[Path, str, str, int | None]] = []

    def block_parse(
        path: Path,
        relative_path: str,
        alexandria_root: str,
        max_source_bytes: int | None = None,
    ) -> None:
        assert threading.current_thread() is not threading.main_thread()
        parse_arguments.append((path, relative_path, alexandria_root, max_source_bytes))
        parse_started.set()
        if not release_parse.wait(timeout=5):
            raise TimeoutError("test did not release the blocking parser")
        parse_finished.set()
        return None

    monkeypatch.setattr(
        graph_note_diagnostics_module,
        "note_index_from_path",
        block_parse,
    )
    service = ObsidianGraphNoteDiagnosticsService(
        repository=repository,
        source=_Source((), ()),
        projection_service=_ProjectionStatusService(),
        vault_config_store=store,
        index_maintenance_coordinator=coordinator,
    )

    async def scenario() -> tuple[bool, bool]:
        rebuild = asyncio.create_task(service.rebuild_note_graph(note_id="source"))
        assert await anyio.to_thread.run_sync(parse_started.wait, 5)
        rebuild.cancel()
        await anyio.lowlevel.checkpoint()
        remains_pending = not rebuild.done()
        lease_remains_owned = coordinator.active_operation == "note_graph_rebuild"
        release_parse.set()
        try:
            with pytest.raises(anyio.get_cancelled_exc_class()):
                await rebuild
        finally:
            release_parse.set()
            assert await anyio.to_thread.run_sync(parse_finished.wait, 5)
        return remains_pending, lease_remains_owned

    remains_pending, lease_remains_owned = anyio.run(scenario)

    assert remains_pending is True
    assert lease_remains_owned is True
    assert repository.lookups == 1
    assert len(parse_arguments) == 1
    assert parse_finished.is_set()
    assert coordinator.active_operation is None


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def _orm_note(note_id: str, path: str) -> ObsidianFileORM:
    return ObsidianFileORM(
        note_id=note_id,
        relative_path=path,
        alexandria_type="context",
        title=note_id,
        status="active",
        tags=[],
        project="heterarchy-alexandria",
        source="test",
        content_hash=f"hash-{note_id}",
        frontmatter_json={},
        body=f"# {note_id}",
        index_status="indexed",
        error_message=None,
        size_bytes=10,
        modified_at=_NOW,
        indexed_at=_NOW,
    )


def _orm_edge(edge_id: str) -> ObsidianEdgeORM:
    return ObsidianEdgeORM(
        edge_id=edge_id,
        source_note_id="source",
        source_path="Alexandria/Source.md",
        target_note_id=None,
        target_path="Alexandria/Missing.md",
        relation="wikilink",
        confidence=0.5,
        source_kind="wikilink",
        created_at=_NOW,
        indexed_at=_NOW,
    )


def test_graph_note_diagnostics_rest_contract_reports_validation_only_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST diagnostics should expose status and per-note unresolved targets."""

    async def seed_database(database_url: str) -> None:
        database = Database(database_url=database_url, create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            session.add(_orm_note("source", "Alexandria/Source.md"))
            await session.flush()
            session.add(_orm_edge("edge-missing"))
            await session.commit()
        finally:
            await session.close()
            await database.shutdown()

    database_url = _database_url()
    anyio.run(seed_database, database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    app = create_app(
        application_container(
            obsidian_vault_path=str(tmp_path / "vault"),
            obsidian_vault_config_path=str(tmp_path / "vault-config.json"),
        )
    )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            build_status = client.get("/obsidian/graph/build/status")
            validation = client.get(
                "/obsidian/graph/notes/validate-links",
                params={"path": "Alexandria/Source.md"},
            )
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)

    assert build_status.status_code == 200
    assert build_status.json()["rebuild_note_graph_supported"] is True
    assert build_status.json()["validation_only_supported"] is True
    assert validation.status_code == 200
    payload = validation.json()
    assert payload["note"]["exists"] is True
    assert payload["note"]["note_id"] == "source"
    assert payload["outgoing"]["parsed_count"] == 1
    assert payload["outgoing"]["resolved_count"] == 0
    assert payload["outgoing"]["unresolved_count"] == 1
    assert payload["outgoing"]["unresolved_targets"][0]["edge_id"] == "edge-missing"
    assert payload["outgoing"]["unresolved_targets"][0]["code"] == "missing_target_note"
    assert payload["projection"]["status"] == "ready"
