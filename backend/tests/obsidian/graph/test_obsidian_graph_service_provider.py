"""Provider-only Obsidian related-note service contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import anyio
import pytest
from fastapi import HTTPException
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianIndexStatus,
    ObsidianRelationType,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.infrastructure.repositories.obsidian_index_query_store import (
    ObsidianIndexQueryStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository_delegates import (
    ObsidianIndexQueryRepositoryDelegate,
)
from app.obsidian.interface.routers.obsidian_note_router import related_obsidian_notes
from app.shared.exceptions.obsidian_exceptions import ObsidianGraphUnavailableError


class _IndexNotes:
    def __init__(self, notes: tuple[ObsidianNote, ...]) -> None:
        self._by_id = {note.note_id: note for note in notes}
        self._by_path = {note.relative_path: note for note in notes}

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        return self._by_id.get(note_id)

    async def get_by_path(self, relative_path: str) -> ObsidianNote | None:
        return self._by_path.get(relative_path)


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
