"""Provider-only Obsidian related-note service contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote, ObsidianRelatedNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianIndexStatus,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import ObsidianGraphDirection
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianFileORM
from app.obsidian.infrastructure.repositories.obsidian_index_query_store import (
    ObsidianIndexQueryStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository_delegates import (
    ObsidianIndexQueryRepositoryDelegate,
)
from app.obsidian.interface.routers.notes.read_router import related_obsidian_notes
from app.shared.exceptions.obsidian_exceptions import ObsidianGraphUnavailableError


class _IndexNotes:
    def __init__(self, notes: tuple[ObsidianNote, ...]) -> None:
        self._by_id = {note.note_id: note for note in notes}
        self._by_path = {note.relative_path: note for note in notes}

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        return self._by_id.get(note_id)

    async def get_by_ids(self, note_ids: tuple[str, ...]) -> tuple[ObsidianNote, ...]:
        return tuple(
            self._by_id[note_id] for note_id in note_ids if note_id in self._by_id
        )

    async def get_by_path(self, relative_path: str) -> ObsidianNote | None:
        return self._by_path.get(relative_path)


class _ScalarRows:
    def __init__(self, rows: tuple[ObsidianFileORM, ...]) -> None:
        self._rows = rows

    def all(self) -> list[ObsidianFileORM]:
        return list(self._rows)


class _CountingSession:
    """Persistence-boundary fake that records point reads and SQL round trips."""

    def __init__(
        self,
        point_rows: dict[str, ObsidianFileORM],
        bulk_rows: tuple[ObsidianFileORM, ...],
    ) -> None:
        self._point_rows = point_rows
        self._bulk_rows = bulk_rows
        self.point_reads: list[str] = []
        self.bulk_statements: list[Select[tuple[ObsidianFileORM]]] = []

    async def get(
        self,
        entity: type[ObsidianFileORM],
        ident: str,
    ) -> ObsidianFileORM | None:
        assert entity is ObsidianFileORM
        self.point_reads.append(ident)
        return self._point_rows.get(ident)

    async def scalars(
        self,
        statement: Select[tuple[ObsidianFileORM]],
    ) -> _ScalarRows:
        self.bulk_statements.append(statement)
        return _ScalarRows(self._bulk_rows)


class _GraphRelatedNotes:
    def __init__(self, results: tuple[ObsidianGraphRelatedNote, ...]) -> None:
        self._results = results

    async def related_notes(
        self,
        note_id: str,
        limit: int,
    ) -> tuple[ObsidianGraphRelatedNote, ...]:
        assert note_id == "source"
        assert limit == 4
        return self._results


def _note(note_id: str) -> ObsidianNote:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    return ObsidianNote(
        note_id=note_id,
        relative_path=f"Alexandria/{note_id}.md",
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=note_id,
        status="active",
        tags=(),
        project="heterarchy-alexandria",
        source=None,
        content_hash=note_id,
        frontmatter={},
        body=f"# {note_id}",
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=10,
        modified_at=now,
        indexed_at=now,
    )


def _row(note: ObsidianNote) -> ObsidianFileORM:
    return ObsidianFileORM(
        note_id=note.note_id,
        relative_path=note.relative_path,
        alexandria_type=note.alexandria_type.value,
        title=note.title,
        status=note.status,
        tags=list(note.tags),
        project=note.project,
        source=note.source,
        content_hash=note.content_hash,
        source_hash=note.source_hash,
        frontmatter_json=dict(note.frontmatter),
        body=note.body,
        index_status=note.index_status.value,
        error_message=note.error_message,
        size_bytes=note.size_bytes,
        modified_at=note.modified_at,
        indexed_at=note.indexed_at,
    )


async def _active_graph() -> FakeObsidianGraphProjectionRepository:
    repository = FakeObsidianGraphProjectionRepository()
    await repository.start_rebuild(run_id="active", projection_version=1)
    await repository.write_rebuild_batch(
        run_id="active",
        projection_version=1,
        batch=ObsidianGraphProjection(
            nodes=tuple(
                ObsidianGraphProjectionNode(
                    note_id=note_id,
                    relative_path=f"Alexandria/{note_id}.md",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    title=note_id,
                    status="active",
                    project="heterarchy-alexandria",
                )
                for note_id in ("source", "target")
            ),
            edges=(
                ObsidianGraphProjectionEdge(
                    edge_id="edge-source-target",
                    source_note_id="source",
                    source_path="Alexandria/source.md",
                    target_note_id="target",
                    target_path="Alexandria/target.md",
                    relation=ObsidianRelationType.CITES,
                    confidence=0.9,
                    source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
                ),
            ),
        ),
    )
    await repository.complete_rebuild(run_id="active", projection_version=1)
    return repository


def test_service_hydrates_provider_traversal_without_reindexing() -> None:
    async def scenario() -> tuple[str, str, str]:
        source = _note("source")
        target = _note("target")
        service = ObsidianGraphService(
            repository=cast(
                IObsidianIndexQueryRepository, _IndexNotes((source, target))
            ),
            graph_repository=await _active_graph(),
        )
        related = await service.related_notes_by_path(source.relative_path)
        return (
            related[0].note.note_id,
            related[0].relation.value,
            related[0].direction,
        )

    assert anyio.run(scenario) == ("target", "cites", "outgoing")


def test_disabled_service_raises_explicit_graph_unavailable_error() -> None:
    service = ObsidianGraphService(
        repository=cast(IObsidianIndexQueryRepository, _IndexNotes((_note("source"),))),
        graph_repository=None,
    )

    with pytest.raises(ObsidianGraphUnavailableError):
        anyio.run(service.related_notes, "source")


def test_related_route_maps_missing_graph_projection_to_503() -> None:
    service = ObsidianGraphService(
        repository=cast(IObsidianIndexQueryRepository, _IndexNotes((_note("source"),))),
        graph_repository=None,
    )

    async def scenario() -> None:
        await related_obsidian_notes(note_id="source", limit=10, service=service)

    with pytest.raises(HTTPException) as raised:
        anyio.run(scenario)

    assert raised.value.status_code == 503
    assert "projection is unavailable" in str(raised.value.detail)


def test_postgres_index_query_api_has_no_related_traversal_surface() -> None:
    assert not hasattr(IObsidianIndexQueryRepository, "related_notes")
    assert not hasattr(ObsidianIndexQueryStore, "related_notes")
    assert not hasattr(ObsidianIndexQueryRepositoryDelegate, "related_notes")


def test_related_hydration_batches_ids_and_preserves_graph_results() -> None:
    async def scenario() -> tuple[list[ObsidianRelatedNote], _CountingSession]:
        source = _note("source")
        target_a = _note("target-a")
        target_b = _note("target-b")
        session = _CountingSession(
            point_rows={"source": _row(source)},
            # Deliberately return rows in an order different from graph results;
            # the missing graph target is intentionally absent from persistence.
            bulk_rows=(_row(target_a), _row(target_b)),
        )
        graph_repository = _GraphRelatedNotes(
            (
                ObsidianGraphRelatedNote(
                    note_id="target-b",
                    edge_id="edge-b-first",
                    relation=ObsidianRelationType.CITES,
                    source_kind=ObsidianEdgeSourceKind.FRONTMATTER,
                    direction=ObsidianGraphDirection.OUTGOING,
                    score=0.91,
                ),
                ObsidianGraphRelatedNote(
                    note_id="missing",
                    edge_id="edge-missing",
                    relation=ObsidianRelationType.SUPPORTS,
                    source_kind=ObsidianEdgeSourceKind.USER_APPROVED,
                    direction=ObsidianGraphDirection.INCOMING,
                    score=0.82,
                ),
                ObsidianGraphRelatedNote(
                    note_id="target-a",
                    edge_id="edge-a",
                    relation=ObsidianRelationType.DERIVED_FROM,
                    source_kind=ObsidianEdgeSourceKind.WIKILINK,
                    direction=ObsidianGraphDirection.INCOMING,
                    score=0.73,
                ),
                ObsidianGraphRelatedNote(
                    note_id="target-b",
                    edge_id="edge-b-second",
                    relation=ObsidianRelationType.SUPERSEDES,
                    source_kind=ObsidianEdgeSourceKind.INFERRED,
                    direction=ObsidianGraphDirection.OUTGOING,
                    score=0.64,
                ),
            )
        )
        service = ObsidianGraphService(
            repository=cast(
                IObsidianIndexQueryRepository,
                ObsidianIndexQueryStore(cast(AsyncSession, session)),
            ),
            graph_repository=cast(IObsidianGraphProjectionRepository, graph_repository),
        )
        related = await service.related_notes("source", limit=4)
        return related, session

    related, session = anyio.run(scenario)

    assert [item.note.note_id for item in related] == [
        "target-b",
        "target-a",
        "target-b",
    ]
    assert [
        (
            item.relation,
            item.source_kind,
            item.direction,
            item.score,
            item.edge_id,
        )
        for item in related
    ] == [
        (
            ObsidianRelationType.CITES,
            ObsidianEdgeSourceKind.FRONTMATTER,
            ObsidianGraphDirection.OUTGOING.value,
            0.91,
            "edge-b-first",
        ),
        (
            ObsidianRelationType.DERIVED_FROM,
            ObsidianEdgeSourceKind.WIKILINK,
            ObsidianGraphDirection.INCOMING.value,
            0.73,
            "edge-a",
        ),
        (
            ObsidianRelationType.SUPERSEDES,
            ObsidianEdgeSourceKind.INFERRED,
            ObsidianGraphDirection.OUTGOING.value,
            0.64,
            "edge-b-second",
        ),
    ]
    assert session.point_reads == ["source"]
    assert len(session.bulk_statements) == 1
    compiled = session.bulk_statements[0].compile(dialect=postgresql.dialect())
    assert "obsidian_files.note_id IN" in str(compiled)
    assert tuple(compiled.params["note_id_1"]) == (
        "target-b",
        "missing",
        "target-a",
    )


def test_empty_graph_results_skip_bulk_read_and_empty_query_skips_database() -> None:
    async def scenario() -> tuple[
        list[ObsidianRelatedNote],
        _CountingSession,
        tuple[ObsidianNote, ...],
    ]:
        source = _note("source")
        session = _CountingSession(point_rows={"source": _row(source)}, bulk_rows=())
        query_store = ObsidianIndexQueryStore(cast(AsyncSession, session))
        empty_lookup = await query_store.get_by_ids(())
        service = ObsidianGraphService(
            repository=cast(IObsidianIndexQueryRepository, query_store),
            graph_repository=cast(
                IObsidianGraphProjectionRepository,
                _GraphRelatedNotes(()),
            ),
        )
        related = await service.related_notes("source", limit=4)
        return related, session, empty_lookup

    related, session, empty_lookup = anyio.run(scenario)

    assert empty_lookup == ()
    assert related == []
    assert session.point_reads == ["source"]
    assert session.bulk_statements == []
