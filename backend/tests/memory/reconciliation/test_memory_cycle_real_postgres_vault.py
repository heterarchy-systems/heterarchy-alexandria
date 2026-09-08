"""Real PostgreSQL, native retrieval, and temporary Vault Memory-cycle proof."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import anyio
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.integration.obsidian_canonical_context_gateway import (
    ObsidianCanonicalContextGateway,
)
from app.memory.application.integration.obsidian_context_read_mapper import (
    context_record_from_obsidian_note,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.candidates.context_memory_candidate_recall_source import (
    ContextMemoryCandidateRecallSource,
)
from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.cycles.memory_cycle_service import (
    MemoryCycleService,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    MemoryReconciliationApplyService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.application.reconciliation.runtime.memory_existing_reconciliation_service import (
    MemoryExistingReconciliationService,
)
from app.memory.application.reconciliation.runtime.obsidian_memory_canonical_mutation_gateway import (
    ObsidianMemoryCanonicalMutationGateway,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.context_read_models import ContextPack, ContextRecord
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleOperation,
    MemoryCycleStatus,
)
from app.memory.infrastructure.models.reconciliation_models import (
    MemoryReconciliationPlanORM,
)
from app.memory.infrastructure.providers.native_extension_loader import (
    create_native_context_retrieval_kernel_provider,
)
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_search_source import (
    SqlAlchemyObsidianContextSearchSource,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_schema import (
    MemoryCycleResponseSchema,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError
from app.shared.exceptions.memory_cycle_exceptions import (
    MemoryCycleRecoveryRequiredError,
    MemoryCycleValidationError,
)
from app.shared.infrastructure.database import Database
from app.shared.infrastructure.postgres_advisory_lock import PostgresAdvisoryLock


@dataclass
class _SelectedContextPort:
    """Expose selected canonical records while delegating real retrieval/get."""

    delegate: ContextService
    records: tuple[ContextRecord, ...]

    async def list_contexts(
        self,
        limit: int = 50,
        offset: int = 0,
        project: str | None = None,
        scope: ContextScope | None = None,
        workspace_id: str | None = None,
        include_archived: bool = False,
        **_: object,
    ) -> tuple[list[ContextRecord], int]:
        """Return the bounded source set through the real selected records."""
        values = [
            record
            for record in self.records
            if (project is None or record.project == project)
            and (scope is None or record.scope is scope)
            and (workspace_id is None or record.workspace_id == workspace_id)
            and (include_archived or not record.is_archived)
        ]
        return values[offset : offset + limit], len(values)

    async def get(self, context_id: str) -> ContextRecord:
        """Delegate canonical Context reads to the real ContextService."""
        return await self.delegate.get(context_id)

    async def search(self, **kwargs: object) -> ContextPack:
        """Delegate native-backed retrieval to the real ContextService."""
        return await self.delegate.search(**kwargs)


async def _build_cycle(
    database: Database,
    session: AsyncSession,
    vault_path: Path,
    records: tuple[ContextRecord, ...],
) -> MemoryCycleService:
    """Assemble real PostgreSQL, Markdown, native retrieval, and cycle services."""
    config = ObsidianVaultConfigStore(
        default_vault_path=str(vault_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    coordinator = IndexMaintenanceCoordinator(
        process_lock=PostgresAdvisoryLock(
            database.engine,
            namespace="heterarchy-alexandria:test-memory-cycle",
        )
    )
    obsidian = ObsidianService(
        repository=SqlAlchemyObsidianIndexRepository(session=session),
        vault_config_store=config,
        index_maintenance_coordinator=coordinator,
        context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
    )
    canonical_gateway = ObsidianCanonicalContextGateway(obsidian)
    context_service = ContextService(
        repository=SqlAlchemyContextRepository(session=session),
        retrieval_kernel_provider=create_native_context_retrieval_kernel_provider(),
        extra_search_sources=[SqlAlchemyObsidianContextSearchSource(session=session)],
        canonical_context_repository=canonical_gateway,
        index_maintenance_coordinator=coordinator,
    )
    selected_contexts = _SelectedContextPort(context_service, records)
    reconciliation_repository = SqlAlchemyMemoryReconciliationRepository(session)
    recall_service = MemoryCandidateRecallService(
        recall_source=ContextMemoryCandidateRecallSource(context_service),
        repository=reconciliation_repository,
    )
    existing_reconciliation = MemoryExistingReconciliationService(
        context_service=selected_contexts,
        candidate_service=MemoryCandidateService(),
        recall_service=recall_service,
        classifier=MemoryRelationClassifier(),
        plan_service=MemoryReconciliationPlanService(),
        repository=reconciliation_repository,
    )
    compact_service = MemoryCompactService(
        repository=ObsidianMemoryCompactRepository(
            vault_path=vault_path,
            relative_dir="Alexandria/Memory Compacts",
        )
    )
    canonical_mutation = ObsidianMemoryCanonicalMutationGateway(obsidian)
    apply_service = MemoryReconciliationApplyService(
        repository=reconciliation_repository,
        canonical_gateway=canonical_mutation,
    )
    return MemoryCycleService(
        existing_reconciliation_service=existing_reconciliation,
        context_service=context_service,
        source_fence=MemoryCycleSourceFence(
            source=obsidian,
            context_reader=context_service,
        ),
        reconciliation_repository=reconciliation_repository,
        reconciliation_apply_service=apply_service,
        compact_service=compact_service,
        compact_policy=MemoryCompactReconciliationPolicy(),
        index_maintenance_coordinator=coordinator,
        checkpoint_store=ObsidianReportBundleRunStore(vault_path),
        commit_projection=session.commit,
        rollback_projection=session.rollback,
    )


async def _save_context(
    obsidian: ObsidianService,
    *,
    note_id: str,
    title: str,
    body: str,
    claims: list[dict[str, object]],
    scope: str = "PROJECT",
    agent_id: str | None = None,
    user_id: str | None = None,
) -> ContextRecord:
    """Persist one real Context note and map it through canonical source readback."""
    await obsidian.save_note(
        ObsidianSaveNote(
            note_id=note_id,
            title=title,
            body=body,
            alexandria_type=AlexandriaNoteType.CONTEXT,
            project="real-cycle",
            status="active",
            frontmatter={
                "scope": scope,
                "visibility": scope,
                "canonical_claims": json.dumps(claims, separators=(",", ":")),
                "evidence_refs": [f"source:{note_id}"],
                "agent_id": agent_id,
                "user_id": user_id,
            },
        )
    )
    return context_record_from_obsidian_note(await obsidian.read_note(note_id))


def _request(operation: MemoryCycleOperation, *, key: str) -> MemoryCycleRequest:
    """Build one explicit aware test window."""
    now = datetime.now(UTC)
    return MemoryCycleRequest(
        operation=operation,
        project="real-cycle",
        window_start=now - timedelta(days=1),
        window_end=now + timedelta(minutes=5),
        idempotency_key=key,
        max_contexts=100,
    )


def _files(vault_path: Path) -> dict[str, bytes]:
    """Capture all temporary Vault Markdown bytes for dry-run proof."""
    return {
        str(path.relative_to(vault_path)): path.read_bytes()
        for path in vault_path.rglob("*.md")
    }


def test_memory_cycle_real_postgres_vault_clean_apply_replay_and_raw_stale(
    tmp_path: Path,
) -> None:
    """Real source/index/Compact pipeline proves dry-run, apply, replay, and stale rejection."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        async with database.engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await database.initialize()
        vault_path = tmp_path / "real-cycle-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        session = database.session()
        try:
            config = ObsidianVaultConfigStore(
                default_vault_path=str(vault_path),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            coordinator = IndexMaintenanceCoordinator(
                process_lock=PostgresAdvisoryLock(
                    database.engine,
                    namespace="heterarchy-alexandria:test-memory-cycle-fixture",
                )
            )
            obsidian = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_config_store=config,
                index_maintenance_coordinator=coordinator,
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            record = await _save_context(
                obsidian,
                note_id="real-cycle-clean",
                title="Real Cycle Clean",
                body="# Real Cycle Clean\n\nCanonical PostgreSQL source authority.",
                claims=[
                    {
                        "subject": "system",
                        "predicate": "authority",
                        "object": "postgresql",
                        "scope": "PROJECT",
                        "project": "real-cycle",
                    }
                ],
            )
            await session.commit()
            cycle = await _build_cycle(
                database,
                session,
                vault_path,
                records=(record,),
            )
            before_files = _files(vault_path)
            dry_request = _request(MemoryCycleOperation.DRY_RUN, key="real-clean")
            query_count = 0

            def count_query(*_: object) -> None:
                nonlocal query_count
                query_count += 1

            event.listen(
                database.engine.sync_engine, "before_cursor_execute", count_query
            )
            try:
                dry_run = await cycle.execute(dry_request)
            finally:
                event.remove(
                    database.engine.sync_engine,
                    "before_cursor_execute",
                    count_query,
                )
            plan_path = vault_path / ".alexandria" / "report-bundle-runs"
            assert dry_run.status is MemoryCycleStatus.PREVIEW
            assert dry_run.candidate_count == 1
            assert dry_run.elapsed_ms >= 0
            assert dry_run.query_count is None
            assert query_count > 0
            assert not plan_path.exists()
            assert _files(vault_path) == before_files
            plan_count = await session.scalar(
                select(func.count()).select_from(MemoryReconciliationPlanORM)
            )
            assert plan_count == 0

            apply_request = replace(
                dry_request,
                operation=MemoryCycleOperation.APPLY,
                expected_plan_hash=dry_run.plan_hash,
            )
            applied = await cycle.execute(apply_request)
            assert applied.status is MemoryCycleStatus.APPLIED
            compact_paths = list(
                (vault_path / "Alexandria" / "Memory Compacts").rglob("*.md")
            )
            assert len(compact_paths) == 1

            await session.close()
            session = database.session()
            restarted = await _build_cycle(
                database,
                session,
                vault_path,
                records=(record,),
            )
            replay = await restarted.execute(apply_request)
            assert replay.replayed is True
            assert (
                len(list((vault_path / "Alexandria" / "Memory Compacts").rglob("*.md")))
                == 1
            )

            source_path = vault_path / record.context_metadata["relative_path"]
            source_path.write_text(
                source_path.read_text(encoding="utf-8").replace(
                    "status: active",
                    "status: reviewed",
                ),
                encoding="utf-8",
            )
            with pytest.raises(MemoryCycleRecoveryRequiredError):
                await restarted.execute(
                    replace(
                        apply_request,
                        idempotency_key="real-clean-stale",
                    )
                )
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_memory_cycle_real_postgres_vault_contradiction_stays_review_bound(
    tmp_path: Path,
) -> None:
    """Real native classification keeps contradictory source facts review-bound."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        async with database.engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await database.initialize()
        vault_path = tmp_path / "real-contradiction-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        session = database.session()
        try:
            config = ObsidianVaultConfigStore(
                default_vault_path=str(vault_path),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            coordinator = IndexMaintenanceCoordinator(
                process_lock=PostgresAdvisoryLock(
                    database.engine,
                    namespace="heterarchy-alexandria:test-memory-cycle-contradiction",
                )
            )
            obsidian = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_config_store=config,
                index_maintenance_coordinator=coordinator,
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            claim_a = {
                "subject": "service",
                "predicate": "status",
                "object": "healthy",
                "scope": "PROJECT",
                "project": "real-cycle",
            }
            claim_b = {**claim_a, "object": "broken"}
            record_a = await _save_context(
                obsidian,
                note_id="real-cycle-a",
                title="Service status healthy",
                body="# Service\n\nservice status healthy canonical fact; broken status is the competing observation.",
                claims=[claim_a],
            )
            record_b = await _save_context(
                obsidian,
                note_id="real-cycle-b",
                title="Service status broken",
                body="# Service\n\nservice status broken canonical fact; healthy status is the competing observation.",
                claims=[claim_b],
            )
            await session.commit()
            cycle = await _build_cycle(
                database,
                session,
                vault_path,
                records=(record_a, record_b),
            )
            dry_request = _request(
                MemoryCycleOperation.DRY_RUN,
                key="real-contradiction",
            )
            dry_run = await cycle.execute(dry_request)
            assert dry_run.status is MemoryCycleStatus.REVIEW_REQUIRED
            assert dry_run.buckets.contradictions
            assert dry_run.compact_change is not None
            assert dry_run.compact_change.safe_to_publish is False

            applied = await cycle.execute(
                replace(
                    dry_request,
                    operation=MemoryCycleOperation.APPLY,
                    expected_plan_hash=dry_run.plan_hash,
                )
            )
            assert applied.status is MemoryCycleStatus.REVIEW_REQUIRED
            assert applied.compact_change is not None
            assert applied.compact_change.status.value == "DRAFT"
            current = MemoryCompactService(
                repository=ObsidianMemoryCompactRepository(
                    vault_path=vault_path,
                    relative_dir="Alexandria/Memory Compacts",
                )
            )
            with pytest.raises(MemoryCompactNotFoundError):
                await current.current(project="real-cycle")
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_memory_cycle_real_project_scope_excludes_agent_user_and_rejects_scope(
    tmp_path: Path,
) -> None:
    """Project CURRENT Compact input excludes same-project agent/user Contexts."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        async with database.engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await database.initialize()
        vault_path = tmp_path / "real-scope-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        session = database.session()
        try:
            config = ObsidianVaultConfigStore(
                default_vault_path=str(vault_path),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            coordinator = IndexMaintenanceCoordinator(
                process_lock=PostgresAdvisoryLock(
                    database.engine,
                    namespace="heterarchy-alexandria:test-memory-cycle-scope",
                )
            )
            obsidian = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_config_store=config,
                index_maintenance_coordinator=coordinator,
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            project_record = await _save_context(
                obsidian,
                note_id="real-scope-project",
                title="Project authority",
                body="# Project\n\nproject-scope-token",
                claims=[],
            )
            await _save_context(
                obsidian,
                note_id="real-scope-agent",
                title="Agent authority",
                body="# Agent\n\nproject-scope-token agent-only",
                claims=[],
                scope="AGENT",
                agent_id="agent-a",
            )
            await _save_context(
                obsidian,
                note_id="real-scope-user",
                title="User authority",
                body="# User\n\nproject-scope-token user-only",
                claims=[],
                scope="USER",
                user_id="user-a",
            )
            await session.commit()
            cycle = await _build_cycle(
                database,
                session,
                vault_path,
                records=(project_record,),
            )
            dry_request = _request(MemoryCycleOperation.DRY_RUN, key="real-scope")
            dry_run = await cycle.execute(dry_request)
            assert dry_run.candidate_count == 1
            assert [item.context_id for item in dry_run.source_snapshot] == [
                "obsidian:real-scope-project"
            ]
            with pytest.raises(MemoryCycleValidationError):
                await cycle.execute(
                    replace(
                        dry_request,
                        scope=ContextScope.AGENT,
                        idempotency_key="bad-scope",
                    )
                )
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_memory_cycle_real_performance_scales_and_writes_evidence(
    tmp_path: Path,
) -> None:
    """Measure bounded real-cycle latency, SQL statements, and payload size."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        async with database.engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await database.initialize()
        vault_path = tmp_path / "real-performance-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        session = database.session()
        try:
            config = ObsidianVaultConfigStore(
                default_vault_path=str(vault_path),
                default_alexandria_root="Alexandria",
                config_path=None,
            )
            coordinator = IndexMaintenanceCoordinator(
                process_lock=PostgresAdvisoryLock(
                    database.engine,
                    namespace="heterarchy-alexandria:test-memory-cycle-performance",
                )
            )
            obsidian = ObsidianService(
                repository=SqlAlchemyObsidianIndexRepository(session=session),
                vault_config_store=config,
                index_maintenance_coordinator=coordinator,
                context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
            )
            records = tuple(
                [
                    await _save_context(
                        obsidian,
                        note_id=f"real-performance-{index}",
                        title=f"Performance source {index}",
                        body=(
                            f"# Performance source {index}\n\n"
                            f"cycle-performance-token-{index}"
                        ),
                        claims=[],
                    )
                    for index in range(10)
                ]
            )
            await session.commit()
            metrics: list[dict[str, object]] = []
            for scale in (2, 10):
                cycle = await _build_cycle(
                    database,
                    session,
                    vault_path,
                    records=records[:scale],
                )
                dry_request = _request(
                    MemoryCycleOperation.DRY_RUN,
                    key=f"performance-{scale}",
                )
                dry_request = replace(dry_request, max_contexts=scale)

                async def measured(
                    operation: MemoryCycleRequest,
                    cycle_service: MemoryCycleService,
                ) -> tuple[object, float, int, int]:
                    statement_count = 0

                    def count_statement(*_: object) -> None:
                        nonlocal statement_count
                        statement_count += 1

                    event.listen(
                        database.engine.sync_engine,
                        "before_cursor_execute",
                        count_statement,
                    )
                    started = perf_counter()
                    try:
                        result = await cycle_service.execute(operation)
                    finally:
                        event.remove(
                            database.engine.sync_engine,
                            "before_cursor_execute",
                            count_statement,
                        )
                    payload = MemoryCycleResponseSchema.from_entity(result)
                    return (
                        result,
                        (perf_counter() - started) * 1000,
                        statement_count,
                        len(payload.model_dump_json().encode("utf-8")),
                    )

                dry_result, dry_latency, dry_sql, dry_bytes = await measured(
                    dry_request,
                    cycle,
                )
                apply_request = replace(
                    dry_request,
                    operation=MemoryCycleOperation.APPLY,
                    expected_plan_hash=dry_result.plan_hash,
                )
                applied, apply_latency, apply_sql, apply_bytes = await measured(
                    apply_request,
                    cycle,
                )
                replayed, replay_latency, replay_sql, replay_bytes = await measured(
                    apply_request,
                    cycle,
                )
                assert dry_result.candidate_count == scale
                assert applied.status is MemoryCycleStatus.APPLIED
                assert replayed.replayed is True
                metrics.append(
                    {
                        "candidate_count": scale,
                        "dry_run_latency_ms": dry_latency,
                        "apply_latency_ms": apply_latency,
                        "replay_latency_ms": replay_latency,
                        "dry_run_sql_statements": dry_sql,
                        "apply_sql_statements": apply_sql,
                        "replay_sql_statements": replay_sql,
                        "dry_run_payload_bytes": dry_bytes,
                        "apply_payload_bytes": apply_bytes,
                        "replay_payload_bytes": replay_bytes,
                        "service_elapsed_ms": dry_result.elapsed_ms,
                        "service_query_count": dry_result.query_count,
                    }
                )

            overflow_request = replace(
                _request(MemoryCycleOperation.DRY_RUN, key="performance-overflow"),
                max_contexts=101,
            )
            with pytest.raises(MemoryCycleValidationError):
                await cycle.execute(overflow_request)
            evidence = {
                "fixture": "real_postgres_temporary_vault_native",
                "scales": metrics,
                "overflow_rejected": True,
            }
            Path("/tmp/alexandria-memory-cycle-performance.json").write_text(
                json.dumps(evidence, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)
