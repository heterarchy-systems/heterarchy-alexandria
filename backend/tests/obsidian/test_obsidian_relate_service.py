"""High-level typed relation and projection convergence regressions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.service.notes.obsidian_relate_service import (
    ObsidianRelateService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionState,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.contracts.obsidian_relation_contracts import (
    ObsidianRelateRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateResult
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianRelationType,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.graph.postgresql_obsidian_graph_projection_repository import (
    PostgreSqlObsidianGraphProjectionRepository,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
)
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.platform.config.app_config import AppConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIdempotencyConflictError,
    ObsidianWriteConflictError,
)
from app.shared.exceptions.obsidian_relation_exceptions import (
    ObsidianRelateInvalidRelationError,
    ObsidianRelateSelfEdgeError,
    ObsidianRelateTargetNotFoundError,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


class _FailingActivationGraphRepository(FakeObsidianGraphProjectionRepository):
    """Inject one graph adapter activation failure after source persistence."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_activation = False

    async def complete_rebuild(
        self,
        *,
        run_id: str,
        projection_version: int,
        issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...] = (),
    ) -> None:
        if self.fail_next_activation:
            self.fail_next_activation = False
            raise RuntimeError("forced graph activation failure")
        await super().complete_rebuild(
            run_id=run_id,
            projection_version=projection_version,
            issue_counts=issue_counts,
        )


def _build_services(
    *,
    tmp_path: Path,
    session: AsyncSession,
    graph_repository: IObsidianGraphProjectionRepository,
    coordinator: IndexMaintenanceCoordinator,
) -> tuple[ObsidianService, ObsidianRelateService]:
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    vault_config = ObsidianVaultConfigStore(
        default_vault_path=str(tmp_path / "vault"),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    obsidian = ObsidianService(
        repository=repository,
        vault_config_store=vault_config,
        context_reindex_manifest_validator=(
            create_native_context_reindex_manifest_validator()
        ),
        index_maintenance_coordinator=coordinator,
    )
    source = SqlAlchemyObsidianGraphProjectionSource(session=session)
    projection = ObsidianGraphProjectionRebuildService(
        config=AppConfig(_env_file=None),
        source_builder=ObsidianGraphProjectionSourceBuilder(
            compute_provider=create_native_obsidian_graph_projection_compute_provider(),
            source=source,
        ),
        repository=graph_repository,
        index_maintenance_coordinator=coordinator,
        run_id_factory=lambda: "relate-graph-run",
    )
    diagnostics = ObsidianGraphNoteDiagnosticsService(
        repository=repository,
        source=source,
        projection_service=projection,
        vault_config_store=vault_config,
        index_maintenance_coordinator=coordinator,
    )
    graph_service = ObsidianGraphService(
        repository=repository,
        graph_repository=graph_repository,
    )
    relate = ObsidianRelateService(
        obsidian_service=obsidian,
        graph_note_diagnostics_service=diagnostics,
        graph_service=graph_service,
        graph_repository=graph_repository,
        vault_config_store=vault_config,
        index_maintenance_coordinator=coordinator,
        commit_projection=session.commit,
        rollback_projection=session.rollback,
    )
    return obsidian, relate


async def _seed_notes(obsidian: ObsidianService) -> tuple[str, str]:
    source = await obsidian.save_note(
        ObsidianSaveNote(
            title="Harness",
            body="# Harness\n",
            alexandria_type=AlexandriaNoteType.JOB_PLAN,
            note_id="harness",
            relative_path="Alexandria/Indexes/Harness.md",
        )
    )
    target = await obsidian.save_note(
        ObsidianSaveNote(
            title="Engineering Harness",
            body="# Engineering Harness\n",
            alexandria_type=AlexandriaNoteType.JOB_PLAN,
            note_id="engineering-harness",
            relative_path="Alexandria/Indexes/Engineering Harness.md",
        )
    )
    return source.note_id, target.note_id


async def _seed_hierarchy(obsidian: ObsidianService) -> tuple[str, ...]:
    """Create Harness -> Engineering Harness -> four package leaves."""
    source_id, target_id = await _seed_notes(obsidian)
    package_ids: list[str] = []
    for note_id, title in (
        ("python-package", "Python Package"),
        ("rust-package", "Rust Package"),
        ("typescript-package", "TypeScript Package"),
        ("python-rust-package", "Python-Rust Package"),
    ):
        note = await obsidian.save_note(
            ObsidianSaveNote(
                title=title,
                body=f"# {title}\n",
                alexandria_type=AlexandriaNoteType.JOB_PLAN,
                note_id=note_id,
                relative_path=f"Alexandria/Indexes/{title}.md",
            )
        )
        package_ids.append(note.note_id)
    return (source_id, target_id, *package_ids)


async def _timed_relate(
    service: ObsidianRelateService,
    request: ObsidianRelateRequest,
    latencies_ms: list[float],
) -> ObsidianRelateResult:
    """Record one end-to-end relation latency for the bounded fixture."""
    started = perf_counter()
    result = await service.relate(request)
    latencies_ms.append((perf_counter() - started) * 1000.0)
    return result


def test_relate_replays_and_converges_harness_hierarchy_through_production_graph(
    tmp_path: Path,
) -> None:
    """One relation must converge through canonical source and native graph reads."""

    async def scenario() -> tuple[
        ObsidianRelateResult,
        ObsidianRelateResult,
        tuple[ObsidianRelateResult, ...],
        ObsidianNote,
        ObsidianGraphProjectionState,
        tuple[
            tuple[ObsidianGraphRelatedNote, ...],
            tuple[ObsidianGraphRelatedNote, ...],
        ],
        tuple[float, ...],
        float,
    ]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            graph_repository = PostgreSqlObsidianGraphProjectionRepository(
                database=database,
                compute_provider=create_native_obsidian_graph_projection_compute_provider(),
            )
            coordinator = IndexMaintenanceCoordinator()
            obsidian, relate = _build_services(
                tmp_path=tmp_path,
                session=session,
                graph_repository=graph_repository,
                coordinator=coordinator,
            )
            hierarchy = await _seed_hierarchy(obsidian)
            source_id, target_id, *package_ids = hierarchy
            request = ObsidianRelateRequest(
                source_note_id=source_id,
                target_note_id=target_id,
                relation=ObsidianRelationType.CONTAINS,
                idempotency_key="harness-hierarchy",
                expected_source_hash=(await obsidian.read_note(source_id)).content_hash,
            )
            edge_latencies_ms: list[float] = []
            started = perf_counter()
            first = await relate.relate(request)
            edge_latencies_ms.append((perf_counter() - started) * 1000.0)
            child_results: list[ObsidianRelateResult] = [
                await _timed_relate(
                    relate,
                    ObsidianRelateRequest(
                        source_note_id=target_id,
                        target_note_id=package_id,
                        relation=ObsidianRelationType.CONTAINS,
                        idempotency_key=f"engineering-harness:{package_id}",
                    ),
                    edge_latencies_ms,
                )
                for package_id in package_ids
            ]
            replay_started = perf_counter()
            replay = await relate.relate(request)
            replay_latency_ms = (perf_counter() - replay_started) * 1000.0
            source = await obsidian.read_note(source_id)
            state = await graph_repository.state()
            outgoing = await graph_repository.related_notes(
                note_id=source_id,
                limit=10,
            )
            incoming = await graph_repository.related_notes(
                note_id=target_id,
                limit=10,
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            first,
            replay,
            tuple(child_results),
            source,
            state,
            (outgoing, incoming),
            tuple(edge_latencies_ms),
            replay_latency_ms,
        )

    (
        first,
        replay,
        child_results,
        source,
        state,
        related,
        edge_latencies_ms,
        replay_latency_ms,
    ) = anyio.run(scenario)
    outgoing, incoming = related
    assert first.completion_status is ObsidianRelateCompletionStatus.COMPLETED
    assert first.operation is ObsidianWriteOperation.UPDATED
    assert all(
        item.completion_status is ObsidianRelateCompletionStatus.COMPLETED
        for item in child_results
    )
    assert first.source_link_verified is True
    assert first.target_backlink_verified is True
    assert first.related_notes_verified is True
    assert first.graph_edge_id is not None
    assert replay.completion_status is ObsidianRelateCompletionStatus.REPLAYED
    assert replay.replayed is True
    contains = source.frontmatter["contains"]
    assert isinstance(contains, list)
    assert len(contains) == 1
    assert "engineering-harness" in str(contains[0])
    assert "[[Alexandria/Indexes/Engineering Harness]]" in source.body
    assert any(
        edge.source_note_id == "harness"
        and edge.target_note_id == "engineering-harness"
        and edge.relation is ObsidianRelationType.CONTAINS
        for edge in state.projection.edges
    )
    assert [item.note_id for item in outgoing] == ["engineering-harness"]
    assert {item.note_id for item in incoming} == {
        "harness",
        "python-package",
        "rust-package",
        "typescript-package",
        "python-rust-package",
    }
    child_edges = {
        (edge.source_note_id, edge.target_note_id, edge.relation)
        for edge in state.projection.edges
        if edge.source_note_id == "engineering-harness"
    }
    expected_child_edges = {
        ("engineering-harness", package_id, ObsidianRelationType.CONTAINS)
        for package_id in (
            "python-package",
            "rust-package",
            "typescript-package",
            "python-rust-package",
        )
    }
    assert expected_child_edges <= child_edges
    assert {
        (edge.source_note_id, edge.target_note_id, edge.relation)
        for edge in state.projection.edges
        if edge.source_note_id == "engineering-harness"
        and edge.relation is ObsidianRelationType.WIKILINK
    } == {
        ("engineering-harness", package_id, ObsidianRelationType.WIKILINK)
        for package_id in (
            "python-package",
            "rust-package",
            "typescript-package",
            "python-rust-package",
        )
    }
    sorted_latencies = sorted(edge_latencies_ms)
    p50 = sorted_latencies[len(sorted_latencies) // 2]
    p95 = sorted_latencies[
        min(len(sorted_latencies) - 1, 95 * len(sorted_latencies) // 100)
    ]
    Path("/tmp/alexandria-relate-performance.json").write_text(
        json.dumps(
            {
                "operation": "relate_harness_hierarchy",
                "storage": "PostgreSQL",
                "compute": "Rust native graph projection",
                "edge_count": len(edge_latencies_ms),
                "end_to_end_latency_ms": {
                    "p50": round(p50, 3),
                    "p95": round(p95, 3),
                    "max": round(max(edge_latencies_ms), 3),
                },
                "replay_latency_ms": round(replay_latency_ms, 3),
                "query_count": "not instrumented",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_relate_replay_rejects_source_body_drift_after_completed_checkpoint(
    tmp_path: Path,
) -> None:
    """A completed relation checkpoint cannot replay over a changed Markdown body."""

    async def scenario() -> None:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            graph_repository = FakeObsidianGraphProjectionRepository()
            obsidian, relate = _build_services(
                tmp_path=tmp_path,
                session=session,
                graph_repository=graph_repository,
                coordinator=IndexMaintenanceCoordinator(),
            )
            source_id, target_id = await _seed_notes(obsidian)
            request = ObsidianRelateRequest(
                source_note_id=source_id,
                target_note_id=target_id,
                relation=ObsidianRelationType.CONTAINS,
                idempotency_key="body-drift-replay",
            )
            completed = await relate.relate(request)
            source = await obsidian.read_note(source_id)
            source_path = tmp_path / "vault" / source.relative_path
            source_path.write_text(
                source_path.read_text(encoding="utf-8") + "\nManual body edit.\n",
                encoding="utf-8",
            )
            with pytest.raises(ObsidianWriteConflictError):
                await relate.relate(request)
        finally:
            await session.close()
            await database.shutdown()

        assert completed.completion_status is ObsidianRelateCompletionStatus.COMPLETED

    anyio.run(scenario)


def test_relate_rejects_invalid_targets_and_idempotency_or_cas_drift(
    tmp_path: Path,
) -> None:
    """Validation and replay fences must fail before source mutation."""

    async def scenario() -> None:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            graph_repository = FakeObsidianGraphProjectionRepository()
            obsidian, relate = _build_services(
                tmp_path=tmp_path,
                session=session,
                graph_repository=graph_repository,
                coordinator=IndexMaintenanceCoordinator(),
            )
            source_id, target_id = await _seed_notes(obsidian)
            missing = ObsidianRelateRequest(
                source_note_id=source_id,
                target_note_id="missing",
                relation=ObsidianRelationType.RELATED,
                idempotency_key="missing-target",
            )
            with pytest.raises(ObsidianRelateTargetNotFoundError):
                await relate.relate(missing)
            with pytest.raises(ObsidianRelateSelfEdgeError):
                await relate.relate(
                    ObsidianRelateRequest(
                        source_note_id=source_id,
                        target_note_id=source_id,
                        relation=ObsidianRelationType.RELATED,
                        idempotency_key="self-edge",
                    )
                )
            with pytest.raises(ObsidianRelateInvalidRelationError):
                await relate.relate(
                    ObsidianRelateRequest(
                        source_note_id=source_id,
                        target_note_id=target_id,
                        relation=ObsidianRelationType.WIKILINK,
                        idempotency_key="body-derived-link",
                    )
                )
            with pytest.raises(ObsidianWriteConflictError):
                await relate.relate(
                    ObsidianRelateRequest(
                        source_note_id=source_id,
                        target_note_id=target_id,
                        relation=ObsidianRelationType.RELATED,
                        idempotency_key="stale-source",
                        expected_source_hash="0" * 64,
                    )
                )
            first = await relate.relate(
                ObsidianRelateRequest(
                    source_note_id=source_id,
                    target_note_id=target_id,
                    relation=ObsidianRelationType.RELATED,
                    idempotency_key="intent-fence",
                )
            )
            with pytest.raises(ObsidianIdempotencyConflictError):
                await relate.relate(
                    ObsidianRelateRequest(
                        source_note_id=source_id,
                        target_note_id=target_id,
                        relation=ObsidianRelationType.EXTENDS,
                        idempotency_key="intent-fence",
                    )
                )
            source = await obsidian.read_note(source_id)
        finally:
            await session.close()
            await database.shutdown()
        assert first.source_link_verified is True
        assert "related" in source.frontmatter
        assert "extends" not in source.frontmatter

    anyio.run(scenario)


def test_relate_returns_projection_warning_and_replay_resumes_after_activation_failure(
    tmp_path: Path,
) -> None:
    """Source durability survives a failed graph activation and later replay."""

    async def scenario() -> tuple[
        ObsidianRelateResult,
        ObsidianNote,
        ObsidianRelateResult,
    ]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            graph_repository = _FailingActivationGraphRepository()
            obsidian, relate = _build_services(
                tmp_path=tmp_path,
                session=session,
                graph_repository=graph_repository,
                coordinator=IndexMaintenanceCoordinator(),
            )
            source_id, target_id = await _seed_notes(obsidian)
            graph_repository.fail_next_activation = True
            request = ObsidianRelateRequest(
                source_note_id=source_id,
                target_note_id=target_id,
                relation=ObsidianRelationType.CONTAINS,
                idempotency_key="activation-retry",
            )
            partial = await relate.relate(request)
            source_after_failure = await obsidian.read_note(source_id)
            replay = await relate.relate(request)
        finally:
            await session.close()
            await database.shutdown()
        return partial, source_after_failure, replay

    partial, source_after_failure, replay = anyio.run(scenario)
    assert (
        partial.completion_status
        is ObsidianRelateCompletionStatus.STORED_WITH_PROJECTION_WARNINGS
    )
    assert partial.source_link_verified is True
    assert "contains" in source_after_failure.frontmatter
    assert replay.completion_status is ObsidianRelateCompletionStatus.REPLAYED
    assert replay.graph_edge_id is not None
