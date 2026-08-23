"""Focused note graph edge rebuild integration test."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.graph.native_obsidian_graph_projection_compute_provider import (
    create_native_obsidian_graph_projection_compute_provider,
)
from app.obsidian.infrastructure.graph.sqlalchemy_obsidian_graph_projection_source import (
    SqlAlchemyObsidianGraphProjectionSource,
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
from app.shared.infrastructure.database import Database
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def test_rebuild_note_graph_replaces_cached_edges_and_activates_projection(
    tmp_path: Path,
) -> None:
    """A canonical file edit should become traversable through one note rebuild."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            store = ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            obsidian = ObsidianService(
                repository=repository,
                vault_config_store=store,
            )
            target = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Graph Target",
                    body="# Graph Target",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    note_id="graph-target",
                    relative_path="Alexandria/Indexes/Graph Target.md",
                )
            )
            owner = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Graph Owner",
                    body="# Graph Owner",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    note_id="graph-owner",
                    relative_path="Alexandria/Indexes/Graph Owner.md",
                )
            )
            graph_repository = FakeObsidianGraphProjectionRepository()
            coordinator = IndexMaintenanceCoordinator()
            source = SqlAlchemyObsidianGraphProjectionSource(session=session)
            projection = ObsidianGraphProjectionRebuildService(
                config=AppConfig(
                    _env_file=None,
                    graph_read_model="neo4j",
                    neo4j_uri="neo4j://example:7687",
                    neo4j_username="neo4j",
                    neo4j_password="local-test-password",
                ),
                source_builder=ObsidianGraphProjectionSourceBuilder(
                    compute_provider=create_native_obsidian_graph_projection_compute_provider(),
                    source=source,
                ),
                repository=graph_repository,
                index_maintenance_coordinator=coordinator,
                run_id_factory=lambda: "note-rebuild-run",
            )
            diagnostics = ObsidianGraphNoteDiagnosticsService(
                repository=repository,
                source=source,
                projection_service=projection,
                vault_config_store=store,
                index_maintenance_coordinator=coordinator,
            )
            owner_path = tmp_path / "vault" / owner.relative_path
            owner_path.write_text(
                owner_path.read_text(encoding="utf-8")
                + "\n[[Alexandria/Indexes/Graph Target.md]]\n",
                encoding="utf-8",
            )

            report = await diagnostics.rebuild_note_graph(note_id=owner.note_id)
            related = await graph_repository.related_notes(
                note_id=target.note_id,
                limit=10,
            )
        finally:
            await session.close()
            await database.shutdown()

        assert report.replace_existing_edges is True
        assert report.projection.status == "completed"
        assert report.validation.outgoing.parsed_count == 1
        assert report.validation.outgoing.resolved_count == 1
        assert report.validation.outgoing.unresolved_count == 0
        assert [item.note_id for item in related] == [owner.note_id]

    anyio.run(scenario)
