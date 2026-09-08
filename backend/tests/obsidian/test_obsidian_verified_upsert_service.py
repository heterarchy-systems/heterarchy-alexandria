"""Real PostgreSQL/Markdown regression tests for verified logical upsert."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.notes.obsidian_verified_upsert_service import (
    ObsidianVerifiedUpsertService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedProjectionStatus,
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertSelector,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.verified_upsert_exceptions import (
    ObsidianVerifiedUpsertRecoveryRequiredError,
)
from app.obsidian.infrastructure.markdown import atomic_markdown_write
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianWriteConflictError
from app.shared.infrastructure.database import Database
from app.shared.infrastructure.postgres_advisory_lock import PostgresAdvisoryLock


def _request(
    *,
    key: str,
    body: str,
    expected: str | None = None,
) -> ObsidianVerifiedUpsertRequest:
    """Build one real managed-note request."""
    return ObsidianVerifiedUpsertRequest(
        identity=ObsidianLogicalIdentity(
            project="Project",
            report="Morning Read",
            date="2026-09-08",
            entity="ETH",
        ),
        title="ETH Morning Read",
        body=body,
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        idempotency_key=key,
        expected_content_hash=expected,
    )


def _real_service(
    database: Database,
    session: AsyncSession,
    vault_path: Path,
    commit_projection: Callable[[], Awaitable[None]] | None = None,
) -> tuple[ObsidianVerifiedUpsertService, ObsidianService]:
    """Assemble the real PostgreSQL/Markdown authority for one session."""
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    store = ObsidianVaultConfigStore(
        default_vault_path=str(vault_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    coordinator = IndexMaintenanceCoordinator(
        process_lock=PostgresAdvisoryLock(
            database.engine,
            namespace="heterarchy-alexandria:test-verified-upsert",
        )
    )
    obsidian = ObsidianService(
        repository=repository,
        vault_config_store=store,
        index_maintenance_coordinator=coordinator,
    )
    service = ObsidianVerifiedUpsertService(
        obsidian_service=obsidian,
        canonical_identity_service=ObsidianCanonicalIdentityService(
            obsidian_service=obsidian,
            vault_config_store=store,
        ),
        vault_config_store=store,
        index_maintenance_coordinator=coordinator,
        commit_projection=(
            session.commit if commit_projection is None else commit_projection
        ),
        rollback_projection=session.rollback,
    )
    return service, obsidian


async def _failing_commit() -> None:
    """Inject a projection transaction failure at the owned commit boundary."""
    raise RuntimeError("projection commit failed")


def test_verified_upsert_real_markdown_postgres_replay_and_cas(
    tmp_path: Path,
) -> None:
    """The high-level write uses real source/index persistence and CAS evidence."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "real-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            service, obsidian = _real_service(database, session, vault_path)
            first = await service.upsert(_request(key="real-1", body="fact"))
            replay = await service.upsert(_request(key="real-1", body="fact"))
            with pytest.raises(ObsidianWriteConflictError):
                await service.upsert(_request(key="real-2", body="changed"))
            updated = await service.upsert(
                _request(
                    key="real-3",
                    body="changed",
                    expected=first.content_hash,
                )
            )
            source = await obsidian.source_snapshot(100)
        finally:
            await session.close()
            await database.shutdown()

        assert first.operation is ObsidianVerifiedUpsertOperation.CREATED
        assert replay.operation is ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY
        assert updated.operation is ObsidianVerifiedUpsertOperation.UPDATED
        assert source.complete is True
        assert len(source.notes) == 1

    anyio.run(scenario)


def test_verified_upsert_real_postgres_lock_serializes_distinct_retries(
    tmp_path: Path,
) -> None:
    """Two independent sessions converge on one active logical Markdown note."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session_a = database.session()
        session_b = database.session()
        vault_path = tmp_path / "concurrent-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            service_a, obsidian_a = _real_service(database, session_a, vault_path)
            service_b, _ = _real_service(database, session_b, vault_path)
            first, second = await asyncio.gather(
                service_a.upsert(_request(key="concurrent-a", body="fact")),
                service_b.upsert(_request(key="concurrent-b", body="fact")),
            )
            source = await obsidian_a.source_snapshot(100)
        finally:
            await session_a.close()
            await session_b.close()
            await database.shutdown()

        assert {first.operation, second.operation} == {
            ObsidianVerifiedUpsertOperation.CREATED,
            ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY,
        }
        assert source.complete is True
        assert len(source.notes) == 1

    anyio.run(scenario)


def test_verified_upsert_unknown_outcome_source_deletion_blocks_retry(
    tmp_path: Path,
) -> None:
    """An admitted unknown create never falls through to a fresh mutation."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "recovery-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            failing, _ = _real_service(
                database,
                session,
                vault_path,
                commit_projection=_failing_commit,
            )
            degraded = await failing.upsert(_request(key="unknown-create", body="fact"))
            source_path = vault_path / degraded.canonical_path
            assert source_path.exists()
            source_path.unlink()

            recovered, _ = _real_service(database, session, vault_path)
            with pytest.raises(ObsidianVerifiedUpsertRecoveryRequiredError):
                await recovered.upsert(_request(key="unknown-create", body="fact"))
            assert not source_path.exists()
        finally:
            await session.close()
            await database.shutdown()

    anyio.run(scenario)


def test_verified_upsert_fsync_failure_keeps_source_outcome_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-replace directory fsync failure cannot become verified storage."""

    sync_calls = 0

    def fail_directory_sync(path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if path.name == "ETH":
            raise OSError(f"directory fsync failed after atomic replace: {path}")

    monkeypatch.setattr(atomic_markdown_write, "_sync_directory", fail_directory_sync)

    async def scenario() -> tuple[
        ObsidianVerifiedProjectionStatus, bool, tuple[str, ...], bool
    ]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "fsync-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            service, _ = _real_service(database, session, vault_path)
            result = await service.upsert(_request(key="fsync-unknown", body="fact"))
            source_path = vault_path / result.canonical_path
            source_exists = source_path.exists()
            recovered, _ = _real_service(database, session, vault_path)
            try:
                await recovered.upsert(_request(key="fsync-unknown", body="fact"))
            except ObsidianVerifiedUpsertRecoveryRequiredError:
                replay_blocked = True
            else:
                replay_blocked = False
        finally:
            await session.close()
            await database.shutdown()
        return (
            result.storage_status,
            result.readback_verified,
            result.warnings,
            (source_exists and replay_blocked),
        )

    storage_status, readback_verified, warnings, durable_replay_blocked = anyio.run(
        scenario
    )

    assert storage_status is ObsidianVerifiedProjectionStatus.UNKNOWN
    assert readback_verified is True
    assert "SOURCE_WRITE_OUTCOME_UNKNOWN" in warnings
    assert durable_replay_blocked is True


def test_verified_upsert_verify_reads_real_source_without_mutation_lease(
    tmp_path: Path,
) -> None:
    """Verify returns source/index evidence through the observational path."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "verify-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            service, _ = _real_service(database, session, vault_path)
            await service.upsert(_request(key="verify-1", body="fact"))
            result = await service.verify(
                ObsidianVerifiedUpsertSelector(
                    identity=ObsidianLogicalIdentity(
                        project="Project",
                        report="Morning Read",
                        date="2026-09-08",
                        entity="ETH",
                    )
                )
            )
        finally:
            await session.close()
            await database.shutdown()

        assert result.source_readable is True
        assert result.indexed is True
        assert result.duplicate_safe is True

    anyio.run(scenario)
