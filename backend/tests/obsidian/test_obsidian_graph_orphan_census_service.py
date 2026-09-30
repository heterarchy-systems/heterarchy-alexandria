"""Graph orphan census service authority and provenance tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest

from app.obsidian.application.graph.diagnostics.obsidian_graph_orphan_census_service import (
    ObsidianGraphOrphanCensusService,
)
from app.obsidian.domain.contracts.obsidian_graph_diagnostics_contracts import (
    ObsidianGraphDiagnosticsResult,
    ObsidianGraphOrphanDiagnostic,
    ObsidianGraphSuggestionDiagnostic,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionState,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianIndexStatus,
    ObsidianRelationType,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class _GraphRepository:
    def __init__(self) -> None:
        self.run_id = "graph-run-1"
        self.initialized = True
        self.include_orphan = True

    async def state(self) -> ObsidianGraphProjectionState:
        return ObsidianGraphProjectionState(
            initialized=self.initialized,
            run_id=self.run_id,
            projection_version=1,
            projection=ObsidianGraphProjection(
                nodes=(
                    ObsidianGraphProjectionNode(
                        note_id="seed",
                        relative_path="Contexts/seed.md",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        title="Seed",
                        status="active",
                        project="p",
                    ),
                    ObsidianGraphProjectionNode(
                        note_id="candidate",
                        relative_path="Contexts/candidate.md",
                        alexandria_type=AlexandriaNoteType.CONTEXT,
                        title="Candidate",
                        status="active",
                        project="p",
                    ),
                    *(
                        (
                            ObsidianGraphProjectionNode(
                                note_id="orphan",
                                relative_path="Contexts/orphan.md",
                                alexandria_type=AlexandriaNoteType.CONTEXT,
                                title="Orphan",
                                status="active",
                                project="p",
                            ),
                        )
                        if self.include_orphan
                        else ()
                    ),
                ),
                edges=(
                    ObsidianGraphProjectionEdge(
                        edge_id="edge-1",
                        source_note_id="seed",
                        source_path="Contexts/seed.md",
                        target_note_id="candidate",
                        target_path="Contexts/candidate.md",
                        relation=ObsidianRelationType.WIKILINK,
                        confidence=1.0,
                        source_kind=ObsidianEdgeSourceKind.WIKILINK,
                    ),
                ),
            ),
        )


class _IndexRepository:
    def __init__(self, notes: tuple[ObsidianNote, ...]) -> None:
        self._notes = notes

    async def list_indexed_notes(self) -> tuple[ObsidianNote, ...]:
        return self._notes

    async def get_by_id(self, note_id: str) -> ObsidianNote | None:
        return next((note for note in self._notes if note.note_id == note_id), None)

    async def get_by_path(self, path: str) -> ObsidianNote | None:
        return next((note for note in self._notes if note.relative_path == path), None)


class _SourceReader:
    def __init__(self, notes: tuple[ObsidianNote, ...]) -> None:
        self._notes = {note.note_id: note for note in notes}

    async def read_note(self, note_id: str) -> ObsidianNote:
        return self._notes[note_id]

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        return next(
            note for note in self._notes.values() if note.relative_path == relative_path
        )


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    def compute(self, *, notes, edges, orphan_request, suggestion_request):
        self.calls += 1
        if suggestion_request is not None:
            return ObsidianGraphDiagnosticsResult(
                contract_version=1,
                graph_compute_version=1,
                suggestions=(
                    ObsidianGraphSuggestionDiagnostic(
                        candidate_note_id="candidate",
                        candidate_path="Contexts/candidate.md",
                        candidate_title="Candidate",
                        relation="related",
                        confidence=0.75,
                        shared_tags=("topic",),
                        shared_neighbor_count=1,
                        title_overlap_tokens=("candidate",),
                        explanation="shared tags: topic",
                    ),
                ),
            )
        return ObsidianGraphDiagnosticsResult(
            contract_version=1,
            graph_compute_version=1,
            orphans=(
                ObsidianGraphOrphanDiagnostic(
                    note_id="orphan",
                    relative_path="Contexts/orphan.md",
                    title="Orphan",
                    project="p",
                    in_degree=0,
                    out_degree=0,
                    canonical_parent_count=0,
                    has_wikilink_connectivity=False,
                    debt_kinds=("degree_zero", "missing_canonical_parent"),
                ),
            ),
            total_orphans=1,
        )


class _StatusProvider(_Provider):
    def __init__(self) -> None:
        super().__init__()
        self.has_debt = True

    def compute(self, *, notes, edges, orphan_request, suggestion_request):
        if suggestion_request is not None or self.has_debt:
            return super().compute(
                notes=notes,
                edges=edges,
                orphan_request=orphan_request,
                suggestion_request=suggestion_request,
            )
        return ObsidianGraphDiagnosticsResult(
            contract_version=1,
            graph_compute_version=1,
            orphans=(),
            total_orphans=0,
        )


def _note(note_id: str, path: str, tags: tuple[str, ...] = ()) -> ObsidianNote:
    return ObsidianNote(
        note_id=note_id,
        relative_path=path,
        alexandria_type=AlexandriaNoteType.CONTEXT,
        title=note_id.title(),
        status="active",
        tags=tags,
        project="p",
        source="test",
        content_hash="hash-" + note_id,
        frontmatter={},
        body="body",
        index_status=ObsidianIndexStatus.INDEXED,
        error_message=None,
        size_bytes=4,
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        indexed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _service(tmp_path: Path, provider: _Provider) -> ObsidianGraphOrphanCensusService:
    return ObsidianGraphOrphanCensusService(
        graph_repository=_GraphRepository(),
        vault_config_store=ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path),
            default_alexandria_root="Alexandria",
            config_path=None,
        ),
        compute_provider=provider,
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
        source_reader=_SourceReader(
            (
                _note("seed", "Contexts/seed.md", ("topic",)),
                _note("candidate", "Contexts/candidate.md", ("topic",)),
            )
        ),
    )


def _service_with_graph(
    tmp_path: Path,
    provider: _Provider,
) -> tuple[ObsidianGraphOrphanCensusService, _GraphRepository]:
    graph = _GraphRepository()
    service = ObsidianGraphOrphanCensusService(
        graph_repository=graph,
        vault_config_store=ObsidianVaultConfigStore(
            default_vault_path=str(tmp_path),
            default_alexandria_root="Alexandria",
            config_path=None,
        ),
        compute_provider=provider,
        index_maintenance_coordinator=IndexMaintenanceCoordinator(),
        source_reader=_SourceReader(
            (
                _note("seed", "Contexts/seed.md", ("topic",)),
                _note("candidate", "Contexts/candidate.md", ("topic",)),
                _note("orphan", "Contexts/orphan.md"),
            )
        ),
    )
    return service, graph


def test_orphan_census_uses_native_result_and_records_seen_metadata(
    tmp_path: Path,
) -> None:
    async def scenario():
        provider = _Provider()
        service = _service(tmp_path, provider)
        result = await service.list_orphans(project="p", limit=10)
        return result, provider.calls

    result, calls = anyio.run(scenario)

    assert calls == 1
    assert result.total_orphans == 1
    assert result.orphans[0].debt_kinds == (
        "degree_zero",
        "missing_canonical_parent",
    )
    assert result.orphans[0].first_seen_at is not None
    assert result.orphans[0].last_seen_at is not None
    assert result.orphans[0].first_seen_run_id == "graph-run-1"
    assert result.orphans[0].last_seen_run_id == "graph-run-1"
    assert result.orphans[0].graph_run_id == "graph-run-1"


def test_exact_status_resolves_then_reopens_with_ack_and_history_preserved(
    tmp_path: Path,
) -> None:
    """Current native debt drives RESOLVED/reopen without losing census history."""

    async def scenario():
        provider = _StatusProvider()
        service, graph = _service_with_graph(tmp_path, provider)
        first = await service.list_orphans(project="p", limit=10)
        acknowledged = await service.acknowledge_orphan(
            note_id="orphan",
            decision="ACKNOWLEDGED_STANDALONE",
            acknowledged_by="agent",
        )
        graph.run_id = "graph-run-2"
        provider.has_debt = False
        resolved = await service.get_orphan_status(note_id="orphan")
        graph.run_id = "graph-run-3"
        provider.has_debt = True
        reopened = await service.get_orphan_status(note_id="orphan")
        rescanned = await service.list_orphans(project="p", limit=10)
        return first, acknowledged, resolved, reopened, rescanned

    first, acknowledged, resolved, reopened, rescanned = anyio.run(scenario)

    assert first.orphans[0].status == "OPEN"
    assert acknowledged.decision == "ACKNOWLEDGED_STANDALONE"
    assert resolved.status == "RESOLVED"
    assert resolved.first_seen_run_id == "graph-run-1"
    assert resolved.last_seen_run_id == "graph-run-1"
    assert reopened.status == "ACKNOWLEDGED_STANDALONE"
    assert reopened.first_seen_run_id == "graph-run-1"
    assert reopened.last_seen_run_id == "graph-run-1"
    assert rescanned.orphans[0].status == "ACKNOWLEDGED_STANDALONE"
    assert rescanned.orphans[0].first_seen_run_id == "graph-run-1"
    assert rescanned.orphans[0].last_seen_run_id == "graph-run-3"


def test_exact_status_never_treats_missing_or_uninitialized_projection_as_resolved(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service, graph = _service_with_graph(tmp_path, _StatusProvider())
        graph.initialized = False
        with pytest.raises(ObsidianValidationError):
            await service.get_orphan_status(note_id="orphan")
        graph.initialized = True
        graph.include_orphan = False
        with pytest.raises(ObsidianNotFoundError):
            await service.get_orphan_status(note_id="orphan")

    anyio.run(scenario)


def test_suggestions_require_canonical_seed_and_candidate_reads(tmp_path: Path) -> None:
    async def scenario():
        provider = _Provider()
        service = _service(tmp_path, provider)
        index = _IndexRepository(
            (
                _note("seed", "Contexts/seed.md", ("topic",)),
                _note("candidate", "Contexts/candidate.md", ("topic",)),
            )
        )
        return await service.suggest_relations(
            note_id="seed", limit=5, index_repository=index
        )

    result = anyio.run(scenario)

    assert result.note_id == "seed"
    assert result.suggestions[0].candidate_note_id == "candidate"
    assert result.suggestions[0].candidate_path == "Contexts/candidate.md"


def test_acknowledgement_requires_reason_for_ignored(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(ObsidianValidationError):
            await _service(tmp_path, _Provider()).acknowledge_orphan(
                note_id="orphan",
                decision="IGNORED_WITH_REASON",
            )

    anyio.run(scenario)


def test_acknowledgement_is_read_checked_under_shared_lease(tmp_path: Path) -> None:
    async def scenario():
        service = _service(tmp_path, _Provider())
        first = await service.acknowledge_orphan(
            note_id="orphan",
            decision="ACKNOWLEDGED_STANDALONE",
            acknowledged_by="agent",
        )
        replay = await service.acknowledge_orphan(
            note_id="orphan",
            decision="ACKNOWLEDGED_STANDALONE",
            acknowledged_by="agent",
        )
        with pytest.raises(ObsidianValidationError):
            await service.acknowledge_orphan(
                note_id="orphan",
                decision="IGNORED_WITH_REASON",
                reason="different decision",
                acknowledged_by="agent",
            )
        return first, replay

    first, replay = anyio.run(scenario)

    assert first == replay
