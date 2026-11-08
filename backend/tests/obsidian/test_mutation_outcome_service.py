"""Real PostgreSQL/Markdown tests for the mutation outcome receipt API."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.obsidian.application.notes.mutations.outcome_service import (
    ObsidianMutationOutcomeService,
)
from app.obsidian.application.notes.verified_upsert.obsidian_verified_upsert_service import (
    ObsidianVerifiedUpsertService,
)
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedUpsertCheckpoint,
    ObsidianVerifiedUpsertRequest,
)
from app.obsidian.domain.entities.obsidian_relation import (
    ObsidianRelateCheckpoint,
    ObsidianRelateResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
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
from app.obsidian.interface.schemas.obsidian.obsidian_mutation_outcome_schema import (
    ObsidianMutationOutcomeRequestSchema,
    ObsidianMutationOutcomeResponseSchema,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.database import Database
from app.shared.infrastructure.postgres_advisory_lock import PostgresAdvisoryLock
from app.shared.type_validation.strict_json_value import model_validate_json_value

_VERIFIED_UPSERT_ADAPTER = TypeAdapter(ObsidianVerifiedUpsertCheckpoint)
_RELATE_ADAPTER = TypeAdapter(ObsidianRelateCheckpoint)


def _request(*, key: str, body: str) -> ObsidianVerifiedUpsertRequest:
    """Build one real managed-note request."""
    return ObsidianVerifiedUpsertRequest(
        identity=ObsidianLogicalIdentity(
            project="Project",
            report="Morning Read",
            date="2026-09-30",
            entity="ETH",
        ),
        title="ETH Morning Read",
        body=body,
        alexandria_type=AlexandriaNoteType.JOB_PLAN,
        idempotency_key=key,
    )


def _fixtures(
    database: Database,
    session: AsyncSession,
    vault_path: Path,
) -> tuple[
    ObsidianVerifiedUpsertService,
    ObsidianMutationOutcomeService,
    ObsidianService,
    ObsidianReportBundleRunStore,
]:
    """Assemble the real write service and its read-only receipt reader."""
    repository = SqlAlchemyObsidianIndexRepository(session=session)
    store = ObsidianVaultConfigStore(
        default_vault_path=str(vault_path),
        default_alexandria_root="Alexandria",
        config_path=None,
    )
    coordinator = IndexMaintenanceCoordinator(
        process_lock=PostgresAdvisoryLock(
            database.engine,
            namespace="heterarchy-alexandria:test-mutation-outcome",
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
        commit_projection=session.commit,
        rollback_projection=session.rollback,
    )
    outcome = ObsidianMutationOutcomeService(
        obsidian_service=obsidian,
        vault_config_store=store,
    )
    run_store = ObsidianReportBundleRunStore(vault_path=store.current().vault_path)
    return service, outcome, obsidian, run_store


def _save_checkpoint(
    run_store: ObsidianReportBundleRunStore,
    key: str,
    checkpoint: ObsidianVerifiedUpsertCheckpoint | ObsidianRelateCheckpoint,
) -> None:
    """Persist one crafted fence checkpoint exactly like the writers do."""
    if isinstance(checkpoint, ObsidianVerifiedUpsertCheckpoint):
        run_store.save_typed(key, checkpoint, _VERIFIED_UPSERT_ADAPTER)
    else:
        run_store.save_typed(key, checkpoint, _RELATE_ADAPTER)


def test_mutation_outcome_covers_committed_not_committed_conflicted_unknown(
    tmp_path: Path,
) -> None:
    """Fence states map to truthful COMMITTED / NOT_COMMITTED / CONFLICTED verdicts."""

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
            service, outcome, _obsidian, run_store = _fixtures(
                database, session, vault_path
            )
            first = await service.upsert(_request(key="receipt-1", body="fact"))

            committed = await outcome.verified_upsert_outcome("receipt-1")
            assert committed.status.value == "COMMITTED"
            assert committed.note_id == first.note_id
            assert committed.content_hash == first.content_hash
            assert committed.checkpoint_state == "completed"
            assert committed.operation_identity is not None
            assert len(committed.operation_identity) == 64
            assert committed.committed_at is not None
            assert committed.evidence == ("durable_checkpoint_readback_verified",)

            not_committed = await outcome.verified_upsert_outcome("never-sent")
            assert not_committed.status.value == "NOT_COMMITTED"
            assert not_committed.evidence == ("checkpoint_absent",)

            note = await _obsidian.read_note(first.note_id)
            _save_checkpoint(
                run_store,
                "verified-upsert:receipt-drift",
                ObsidianVerifiedUpsertCheckpoint(
                    state=ObsidianVerifiedCheckpointState.WRITE_STARTED,
                    request_hash="a" * 64,
                    logical_identity=first.logical_identity,
                    canonical_path=note.relative_path,
                    title="ETH Morning Read",
                    body_hash="b" * 64,
                    expected_content_hash=None,
                    target_note_id="ghost-note",
                ),
            )
            conflicted = await outcome.verified_upsert_outcome("receipt-drift")
            assert conflicted.status.value == "CONFLICTED"
            assert conflicted.evidence == ("identity_drift",)

            _save_checkpoint(
                run_store,
                "verified-upsert:receipt-unattributable",
                ObsidianVerifiedUpsertCheckpoint(
                    state=ObsidianVerifiedCheckpointState.WRITE_STARTED,
                    request_hash="c" * 64,
                    logical_identity=first.logical_identity,
                    canonical_path=note.relative_path,
                    title="ETH Morning Read",
                    body_hash="d" * 64,
                    expected_content_hash=None,
                    target_note_id=note.note_id,
                ),
            )
            unknown = await outcome.verified_upsert_outcome("receipt-unattributable")
            assert unknown.status.value == "UNKNOWN"
            assert unknown.evidence == ("outcome_not_attributable",)

            _save_checkpoint(
                run_store,
                "verified-upsert:receipt-unconfirmed",
                ObsidianVerifiedUpsertCheckpoint(
                    state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                    request_hash="e" * 64,
                    logical_identity=first.logical_identity,
                    canonical_path=note.relative_path,
                    title="ETH Morning Read",
                    body_hash="f" * 64,
                    expected_content_hash=None,
                    content_hash="f" * 64,
                    warnings=("projection_commit_failed",),
                ),
            )
            required = await outcome.verified_upsert_outcome("receipt-unconfirmed")
            assert required.status.value == "RECONCILIATION_REQUIRED"
            assert "recorded_content_not_confirmed" in required.evidence
        finally:
            await session.close()
            await database.shutdown()

    asyncio.run(scenario())


def test_relate_mutation_outcome_reports_committed_and_unknown(tmp_path: Path) -> None:
    """Relate receipts read back the recorded relation from canonical sources."""

    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        vault_path = tmp_path / "relate-vault"
        (vault_path / "Alexandria").mkdir(parents=True)
        try:
            _service, outcome, obsidian, run_store = _fixtures(
                database, session, vault_path
            )
            unknown = await outcome.relate_outcome("never-related")
            assert unknown.status.value == "UNKNOWN"
            assert unknown.evidence == ("no_relate_fence_recorded",)

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
            related_source = await obsidian.save_note(
                ObsidianSaveNote(
                    title="Harness",
                    body="# Harness\n",
                    alexandria_type=AlexandriaNoteType.JOB_PLAN,
                    note_id=source.note_id,
                    relative_path=source.relative_path,
                    expected_content_hash=source.content_hash,
                    frontmatter={
                        "related": [
                            {
                                "id": target.note_id,
                                "path": target.relative_path,
                                "relation": ObsidianRelationType.RELATED.value,
                            }
                        ]
                    },
                )
            )
            _save_checkpoint(
                run_store,
                "relate:receipt-relate",
                ObsidianRelateCheckpoint(
                    request_hash="a" * 64,
                    source_note_id=source.note_id,
                    target_note_id=target.note_id,
                    relation=ObsidianRelationType.RELATED,
                    source_content_hash=related_source.content_hash,
                    result=ObsidianRelateResult(
                        completion_status=(ObsidianRelateCompletionStatus.COMPLETED),
                        idempotency_key="receipt-relate",
                        replayed=False,
                        source_note_id=source.note_id,
                        target_note_id=target.note_id,
                        relation=ObsidianRelationType.RELATED,
                        source_path=source.relative_path,
                        target_path=target.relative_path,
                        operation=None,
                        content_hash=related_source.content_hash,
                        storage_status="verified",
                        metadata_status="verified",
                        fts_status="unknown",
                        graph_edge_index_status="unknown",
                        graph_projection_status="unknown",
                        source_link_verified=True,
                        target_backlink_verified=True,
                        related_notes_verified=True,
                    ),
                ),
            )
            committed = await outcome.relate_outcome("receipt-relate")
            assert committed.status.value == "COMMITTED"
            assert committed.note_id == source.note_id
            assert committed.operation_identity == "a" * 64
            assert committed.committed_at is not None
            assert committed.evidence == ("relation_readback_verified",)
        finally:
            await session.close()
            await database.shutdown()

    asyncio.run(scenario())


def test_mutation_outcome_schema_round_trips_backend_json() -> None:
    """The declared response schema consumes the serialized backend payload."""
    payload = {
        "operation": "verified_upsert",
        "idempotency_key": "receipt-1",
        "status": "COMMITTED",
        "checkpoint_state": "completed",
        "canonical_path": "Alexandria/Reports/ETH.md",
        "note_id": "eth",
        "content_hash": "a" * 64,
        "version": None,
        "evidence": ["durable_checkpoint_readback_verified"],
    }
    validated = model_validate_json_value(
        ObsidianMutationOutcomeResponseSchema,
        payload,
    )
    assert validated.status == "COMMITTED"
    assert validated.evidence == ["durable_checkpoint_readback_verified"]

    omitted = model_validate_json_value(
        ObsidianMutationOutcomeResponseSchema,
        {
            "operation": "relate",
            "idempotency_key": "receipt-relate",
            "status": "UNKNOWN",
            "evidence": ["no_relate_fence_recorded"],
        },
    )
    assert omitted.checkpoint_state is None
    assert omitted.canonical_path is None


def test_mutation_outcome_schema_accepts_direct_note_receipt_id() -> None:
    """The public selector supports a namespaced direct receipt lookup."""
    direct = model_validate_json_value(
        ObsidianMutationOutcomeRequestSchema,
        {"mutation_id": "note-write:" + "a" * 64},
    )
    assert direct.operation == "note_write"
    assert direct.idempotency_key is None
    assert direct.mutation_id == "note-write:" + "a" * 64

    legacy = model_validate_json_value(
        ObsidianMutationOutcomeRequestSchema,
        {"operation": "relate", "idempotency_key": "receipt-relate"},
    )
    assert legacy.operation == "relate"
    assert legacy.idempotency_key == "receipt-relate"

    with pytest.raises(ValueError):
        model_validate_json_value(
            ObsidianMutationOutcomeRequestSchema,
            {"mutation_id": "note-write:" + "A" * 64},
        )


def test_mutation_outcome_http_accepts_direct_note_receipt_id_read_only() -> None:
    """The real route exposes direct receipt lookup without a write effect."""
    mutation_id = "note-write:" + "a" * 64
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/obsidian/mutations/outcome",
            json={"mutation_id": mutation_id},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["operation"] == "note_write"
    assert payload["status"] == "NOT_COMMITTED"
    assert payload["mutation_id"] == mutation_id
    assert payload["idempotency_key"] is None

    with pytest.raises(ValueError):
        model_validate_json_value(
            ObsidianMutationOutcomeResponseSchema,
            {
                "operation": "note_write",
                "idempotency_key": "receipt-1",
                "status": "COMMITTED",
                "evidence": ["primary_source_committed"],
                "committed_at": "2026-09-30T00:00:00",
            },
        )
