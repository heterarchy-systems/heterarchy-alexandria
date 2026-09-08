"""Idempotent report bundle orchestration tests."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import anyio
import pytest
from tests.obsidian.graph.fakes.fake_obsidian_graph_projection_repository import (
    FakeObsidianGraphProjectionRepository,
)

from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_source_builder import (
    ObsidianGraphProjectionSourceBuilder,
)
from app.obsidian.application.service.notes.obsidian_report_bundle_service import (
    ObsidianReportBundleService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexService,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleOwner,
    ObsidianReportBundleRequest,
    ObsidianSaveNote,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionIssueCount,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianRelationType,
    ObsidianReportBundleCompletionStatus,
    ObsidianWriteOperation,
)
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
    ObsidianNotFoundError,
)
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


class _FailingActivationGraphRepository(FakeObsidianGraphProjectionRepository):
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
            raise RuntimeError("forced activation failure")
        await super().complete_rebuild(
            run_id=run_id,
            projection_version=projection_version,
            issue_counts=issue_counts,
        )


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def test_report_bundle_is_idempotent_and_verifies_expected_owner_edges(
    tmp_path: Path,
) -> None:
    """A repeated bundle must reuse Source identity and return the same graph state."""

    async def scenario() -> None:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            store = ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            coordinator = IndexMaintenanceCoordinator()
            obsidian = ObsidianService(
                repository=repository,
                vault_config_store=store,
                index_maintenance_coordinator=coordinator,
                context_reindex_manifest_validator=(
                    create_native_context_reindex_manifest_validator()
                ),
            )
            graph_repository = _FailingActivationGraphRepository()
            graph_rebuild = ObsidianGraphProjectionRebuildService(
                config=AppConfig(_env_file=None),
                source_builder=ObsidianGraphProjectionSourceBuilder(
                    compute_provider=create_native_obsidian_graph_projection_compute_provider(),
                    source=SqlAlchemyObsidianGraphProjectionSource(session=session),
                ),
                repository=graph_repository,
                index_maintenance_coordinator=coordinator,
                run_id_factory=lambda: "bundle-graph-run",
            )
            bundle = ObsidianReportBundleService(
                obsidian_service=obsidian,
                vault_reindex_service=ObsidianVaultReindexService(
                    obsidian_service=obsidian,
                    graph_projection_rebuild_service=graph_rebuild,
                ),
                graph_service=ObsidianGraphService(
                    repository=repository,
                    graph_repository=graph_repository,
                ),
                vault_config_store=store,
                index_maintenance_coordinator=coordinator,
            )
            index = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Ethereum Month Index",
                    body="# Ethereum Month Index\n",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    note_id="eth-month-index",
                    relative_path="Alexandria/Indexes/Ethereum Month Index.md",
                )
            )
            hub = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Ethereum Entity Hub",
                    body="# Ethereum Entity Hub\n",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    note_id="eth-entity-hub",
                    relative_path="Alexandria/Indexes/Ethereum Entity Hub.md",
                )
            )
            duplicate = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Prior Ethereum Source",
                    body="# Prior Ethereum Source\n\ndifferent evidence",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path="Alexandria/Contexts/Projects/prior-ethereum.md",
                    project="crypto-intelligence",
                    frontmatter={
                        "scope": "PROJECT",
                        "report_family": "Morning Read",
                        "date": "2026-08-03",
                        "entity": "Ethereum",
                    },
                )
            )
            request = ObsidianReportBundleRequest(
                idempotency_key="ethereum:2026-08-03",
                source=ObsidianSaveNote(
                    title="Ethereum Source",
                    body="# Ethereum Source\n\ncanonical evidence",
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path="Contexts/Projects/Ethereum Source.md",
                    project="crypto-intelligence",
                    frontmatter={
                        "scope": "PROJECT",
                        "report_family": "Morning Read",
                        "date": "2026-08-03",
                        "entity": "Ethereum",
                    },
                ),
                graph_owners=(
                    ObsidianReportBundleOwner(
                        path="Indexes/Ethereum Month Index.md",
                        relation=ObsidianRelationType.CONTAINS,
                    ),
                    ObsidianReportBundleOwner(
                        path="Indexes/Ethereum Entity Hub.md",
                        relation=ObsidianRelationType.CONTAINS,
                    ),
                ),
            )

            first = await bundle.upsert(request)
            replay = await bundle.upsert(request)
            index_after = await obsidian.read_note(index.note_id)
            hub_after = await obsidian.read_note(hub.note_id)
            related = await graph_repository.related_notes(
                note_id=first.source.note.note_id if first.source else "missing",
                limit=10,
            )
            with pytest.raises(ObsidianIdempotencyConflictError):
                await bundle.upsert(
                    replace(
                        request,
                        source=replace(request.source, body="# Changed request"),
                    )
                )
            with pytest.raises(ObsidianIdempotencyConflictError):
                await bundle.upsert(
                    replace(
                        request,
                        source=replace(
                            request.source,
                            expected_content_hash="f" * 64,
                        ),
                    )
                )
            graph_repository.fail_next_activation = True
            failed_rebuild = await bundle.upsert(
                replace(
                    request,
                    idempotency_key="ethereum:2026-08-03:failed-rebuild",
                    source=replace(
                        request.source,
                        body="# Ethereum Source\n\nnew canonical evidence",
                        expected_content_hash=first.source.note.content_hash
                        if first.source
                        else None,
                    ),
                )
            )
        finally:
            await session.close()
            await database.shutdown()

        assert (
            first.completion_status
            is ObsidianReportBundleCompletionStatus.COMPLETED_WITH_WARNINGS
        )
        assert first.source is not None
        assert first.source.operation is ObsidianWriteOperation.CREATED
        assert first.source.note.relative_path == (
            "Alexandria/Contexts/Projects/Ethereum Source.md"
        )
        assert first.graph.expected_incoming_edges == 2
        assert first.graph.verified_incoming_edges == 2
        assert replay.replayed is True
        assert replay.source is not None
        assert replay.source.note.note_id == first.source.note.note_id
        assert replay.source.operation is ObsidianWriteOperation.UNCHANGED
        assert replay.completion_status == first.completion_status
        assert replay.duplicates == first.duplicates == (duplicate.relative_path,)
        assert replay.errors == first.errors
        assert len(replay.owner_writes) == 2
        assert (
            failed_rebuild.completion_status
            is ObsidianReportBundleCompletionStatus.PARTIAL_GRAPH_UNVERIFIED
        )
        assert failed_rebuild.failed_stage == "REBUILD_GRAPH_PROJECTION"
        assert failed_rebuild.errors
        assert {item.note_id for item in related} == {index.note_id, hub.note_id}
        assert len(index_after.frontmatter["contains"]) == 1
        assert len(hub_after.frontmatter["contains"]) == 1

    anyio.run(scenario)


def test_report_bundle_missing_owner_fails_before_source_mutation(
    tmp_path: Path,
) -> None:
    """Owner preflight should prevent a partial Source when an owner is absent."""

    async def scenario() -> None:
        database = Database(database_url=_database_url(), create_schema=True)
        await database.initialize()
        session = database.session()
        try:
            repository = SqlAlchemyObsidianIndexRepository(session=session)
            store = ObsidianVaultConfigStore(
                default_vault_path=str(tmp_path / "vault"),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            coordinator = IndexMaintenanceCoordinator()
            obsidian = ObsidianService(
                repository=repository,
                vault_config_store=store,
                index_maintenance_coordinator=coordinator,
            )
            graph_repository = FakeObsidianGraphProjectionRepository()
            graph_rebuild = ObsidianGraphProjectionRebuildService(
                config=AppConfig(_env_file=None),
                source_builder=ObsidianGraphProjectionSourceBuilder(
                    compute_provider=create_native_obsidian_graph_projection_compute_provider(),
                    source=SqlAlchemyObsidianGraphProjectionSource(session=session),
                ),
                repository=graph_repository,
                index_maintenance_coordinator=coordinator,
            )
            bundle = ObsidianReportBundleService(
                obsidian_service=obsidian,
                vault_reindex_service=ObsidianVaultReindexService(
                    obsidian_service=obsidian,
                    graph_projection_rebuild_service=graph_rebuild,
                ),
                graph_service=ObsidianGraphService(
                    repository=repository,
                    graph_repository=graph_repository,
                ),
                vault_config_store=store,
                index_maintenance_coordinator=coordinator,
            )
            result = await bundle.upsert(
                ObsidianReportBundleRequest(
                    idempotency_key="missing-owner",
                    source=ObsidianSaveNote(
                        title="Must Not Exist",
                        body="# Must Not Exist",
                        alexandria_type=AlexandriaNoteType.JOB_PLAN,
                        relative_path="Jobs/must-not-exist.md",
                    ),
                    graph_owners=(
                        ObsidianReportBundleOwner(path="Indexes/missing.md"),
                    ),
                )
            )
            with pytest.raises(ObsidianNotFoundError):
                await obsidian.read_note_by_path("Alexandria/Jobs/must-not-exist.md")
        finally:
            await session.close()
            await database.shutdown()

        assert (
            result.completion_status
            is ObsidianReportBundleCompletionStatus.FAILED_NO_MUTATION
        )
        assert result.failed_stage == "PREFLIGHT_GRAPH_OWNERS"
        assert result.source is None

    anyio.run(scenario)
