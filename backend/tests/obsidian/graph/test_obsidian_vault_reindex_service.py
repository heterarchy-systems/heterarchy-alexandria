"""Composite Obsidian reindex orchestration and graph freshness regressions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import anyio
import pytest
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildReport,
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexService,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianReindexResult
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
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
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.platform.config.app_config import AppConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def _context_markdown(note_id: str, title: str, body: str) -> str:
    return (
        "---\n"
        "alexandria_type: context\n"
        f"id: {note_id}\n"
        f"title: {title}\n"
        "status: active\n"
        "scope: GLOBAL\n"
        "---\n\n"
        f"# {title}\n\n{body}\n"
    )


class _LockedVaultReindex:
    def __init__(
        self,
        *,
        coordinator: IndexMaintenanceCoordinator,
        events: list[tuple[str, str | None]],
    ) -> None:
        self._coordinator = coordinator
        self._events = events

    async def reindex(self) -> ObsidianReindexResult:
        async with self._coordinator.operation("vault_reindex"):
            self._events.append(("vault_index", self._coordinator.active_operation))
        return ObsidianReindexResult(
            files_seen=2,
            files_indexed=2,
            files_skipped=0,
            stale_marked=0,
        )


class _GraphAfterVaultReindex:
    def __init__(
        self,
        *,
        coordinator: IndexMaintenanceCoordinator,
        events: list[tuple[str, str | None]],
    ) -> None:
        self._coordinator = coordinator
        self._events = events

    async def rebuild(self) -> ObsidianGraphProjectionRebuildReport:
        self._events.append(("graph", self._coordinator.active_operation))
        return ObsidianGraphProjectionRebuildReport(
            status="disabled",
            graph_read_model="disabled",
            run_id="graph-disabled",
            scanned=0,
            indexed=0,
            updated=0,
            skipped=0,
            duration_seconds=0.0,
        )


def test_composite_reindex_runs_graph_after_vault_index_lease_is_released() -> None:
    """Public composite reindex should not nest graph rebuild in the vault-index lease."""
    coordinator = IndexMaintenanceCoordinator()
    events: list[tuple[str, str | None]] = []
    service = ObsidianVaultReindexService(
        obsidian_service=cast(
            ObsidianService,
            _LockedVaultReindex(coordinator=coordinator, events=events),
        ),
        graph_projection_rebuild_service=cast(
            ObsidianGraphProjectionRebuildService,
            _GraphAfterVaultReindex(coordinator=coordinator, events=events),
        ),
    )

    report = anyio.run(service.rebuild)

    assert events == [("vault_index", "vault_reindex"), ("graph", None)]
    assert report.vault_index.files_indexed == 2
    assert report.graph_projection.status == "disabled"
    assert report.graph_projection.graph_read_model == "disabled"


def test_composite_reindex_refreshes_graph_from_new_canonical_markdown(
    tmp_path: Path,
) -> None:
    """Composite rebuild fixes stale graph projections by refreshing the vault index first."""

    async def scenario() -> tuple[list[str], int, int, str]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            obsidian = ObsidianService(
                repository=repository,
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            graph_repository = FakeObsidianGraphProjectionRepository()
            graph_service = ObsidianGraphProjectionRebuildService(
                config=AppConfig(
                    _env_file=None,
                    graph_read_model="neo4j",
                    neo4j_uri="neo4j://example:7687",
                    neo4j_username="neo4j",
                    neo4j_password="local-test-password",
                ),
                source_builder=ObsidianGraphProjectionSourceBuilder(
                    compute_provider=create_native_obsidian_graph_projection_compute_provider(),
                    source=SqlAlchemyObsidianGraphProjectionSource(session=session),
                ),
                repository=graph_repository,
                index_maintenance_coordinator=IndexMaintenanceCoordinator(),
                run_id_factory=lambda: "graph-run",
            )
            composite = ObsidianVaultReindexService(
                obsidian_service=obsidian,
                graph_projection_rebuild_service=graph_service,
            )
            root = tmp_path / "vault" / "Alexandria"
            root.mkdir(parents=True)
            (root / "Source.md").write_text(
                _context_markdown("ctx_source", "Source", "Canonical target."),
                encoding="utf-8",
            )
            (root / "First.md").write_text(
                _context_markdown("ctx_first", "First", "See [[Source]]."),
                encoding="utf-8",
            )
            await obsidian.reindex()
            stale_report = await graph_service.rebuild()

            (root / "Second.md").write_text(
                _context_markdown("ctx_second", "Second", "Also see [[Source]]."),
                encoding="utf-8",
            )
            fresh_report = await composite.rebuild()
            related = await graph_repository.related_notes(
                note_id="ctx_source", limit=10
            )
        finally:
            await session.close()
            await database.shutdown()
        return (
            [item.note_id for item in related],
            stale_report.updated,
            fresh_report.graph_projection.updated,
            fresh_report.graph_projection.status,
        )

    related_note_ids, stale_edges, fresh_edges, status = anyio.run(scenario)

    assert stale_edges == 3
    assert fresh_edges == 5
    assert status == "completed"
    assert set(related_note_ids) == {"ctx_first", "ctx_second"}
    assert len(related_note_ids) == 2


@pytest.mark.parametrize(
    "actions",
    [
        ("source", "index", "hub", "reindex"),
        ("index", "hub", "source", "reindex"),
        ("index", "reindex", "source", "reindex", "hub", "reindex"),
        ("source", "reindex", "index", "hub", "reindex"),
    ],
    ids=("case-a", "case-b", "case-c", "case-d"),
)
def test_report_bundle_order_always_materializes_expected_incoming_edges(
    tmp_path: Path,
    actions: tuple[str, ...],
) -> None:
    """Source/Index/Hub order must not change the final graph projection."""

    async def scenario() -> tuple[set[str], int, int, str]:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            obsidian = ObsidianService(
                repository=repository,
                vault_path=str(tmp_path / "vault"),
                alexandria_root="Alexandria",
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            graph_repository = FakeObsidianGraphProjectionRepository()
            graph_service = ObsidianGraphProjectionRebuildService(
                config=AppConfig(
                    _env_file=None,
                    graph_read_model="neo4j",
                    neo4j_uri="neo4j://example:7687",
                    neo4j_username="neo4j",
                    neo4j_password="local-test-password",
                ),
                source_builder=ObsidianGraphProjectionSourceBuilder(
                    compute_provider=create_native_obsidian_graph_projection_compute_provider(),
                    source=SqlAlchemyObsidianGraphProjectionSource(session=session),
                ),
                repository=graph_repository,
                index_maintenance_coordinator=IndexMaintenanceCoordinator(),
                run_id_factory=lambda: "ordered-graph-run",
            )
            composite = ObsidianVaultReindexService(
                obsidian_service=obsidian,
                graph_projection_rebuild_service=graph_service,
            )
            root = tmp_path / "vault" / "Alexandria" / "Reports"
            source_path = root / "Ethereum Source.md"
            owner_documents = {
                "index": (
                    root / "Ethereum Month Index.md",
                    _context_markdown(
                        "ctx_eth_index",
                        "Ethereum Month Index",
                        "Contains [[Alexandria/Reports/Ethereum Source.md]].",
                    ),
                ),
                "hub": (
                    root / "Ethereum Entity Hub.md",
                    _context_markdown(
                        "ctx_eth_hub",
                        "Ethereum Entity Hub",
                        "Contains [[Alexandria/Reports/Ethereum Source.md]].",
                    ),
                ),
            }
            root.mkdir(parents=True)
            for action in actions:
                if action == "source":
                    source_path.write_text(
                        _context_markdown(
                            "ctx_eth_source",
                            "Ethereum Source",
                            "Canonical Ethereum evidence.",
                        ),
                        encoding="utf-8",
                    )
                elif action == "reindex":
                    await obsidian.reindex()
                else:
                    path, document = owner_documents[action]
                    path.write_text(document, encoding="utf-8")

            report = await composite.rebuild()
            state = await graph_repository.state()
            related = await graph_repository.related_notes(
                note_id="ctx_eth_source",
                limit=10,
            )
        finally:
            await session.close()
            await database.shutdown()

        incoming_edges = {
            edge.source_note_id
            for edge in state.projection.edges
            if edge.target_note_id == "ctx_eth_source"
        }
        return (
            incoming_edges,
            len(related),
            report.graph_projection.issue_total,
            report.graph_projection.status,
        )

    incoming, related_count, unresolved, status = anyio.run(scenario)

    assert incoming == {"ctx_eth_index", "ctx_eth_hub"}
    assert related_count == 2
    assert unresolved == 0
    assert status == "completed"
