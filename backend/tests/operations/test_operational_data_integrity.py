"""Operational data-integrity diagnostics remain separate from readiness."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import anyio
import pytest
from pytest import MonkeyPatch
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.memory.application.contexts.records.context_service_ports import (
    ContextReadinessPort,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianDataIntegrityPort,
    ObsidianReadinessPort,
)
from app.obsidian.application.service.vault.obsidian_vault_inventory_service import (
    ObsidianVaultInventoryService,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianVaultLocation,
    ObsidianVaultStatus,
)
from app.obsidian.domain.entities.obsidian_raw_source_snapshot import (
    ObsidianRawSourceFile,
    ObsidianRawSourceSnapshot,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.operations.application.readiness import operational_data_integrity_service
from app.operations.application.readiness.operational_data_integrity_service import (
    OperationalDataIntegrityService,
    _WarningAccumulator,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.application.readiness.policy.operational_overall_readiness import (
    overall_readiness_status,
)
from app.operations.domain.entities.operational_data_integrity import (
    unchecked_data_integrity_snapshot,
)
from app.operations.domain.event_enum.operational_data_integrity_enums import (
    OperationalDataIntegrityStatus,
    OperationalDataIntegrityWarningCode,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.operations.interface.schemas.operations.operational_readiness_detail_schema import (
    OperationalReadinessSnapshotResponse,
)
from app.shared.infrastructure.database import Database


class _HealthyContextService(ContextReadinessPort):
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.HEALTHY,
            default_strategy=RagStrategy.HYBRID,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=[],
        )


class _InventoryObsidianService(ObsidianReadinessPort, ObsidianDataIntegrityPort):
    def __init__(
        self,
        status: ObsidianVaultStatus,
        source_snapshot: ObsidianRawSourceSnapshot,
    ) -> None:
        self._status = status
        self._source_snapshot = source_snapshot

    async def status(self) -> ObsidianVaultStatus:
        return self._status

    def vault_location(self) -> ObsidianVaultLocation:
        return ObsidianVaultLocation(
            vault_path=self._status.vault_path,
            alexandria_root=self._status.alexandria_root,
        )

    async def raw_source_snapshot(self) -> ObsidianRawSourceSnapshot:
        return self._source_snapshot


def _managed_note(
    *,
    vault: Path,
    relative_path: str,
    frontmatter: str,
) -> str:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n\nBody\n", encoding="utf-8")
    return relative_path


def _raw_source_snapshot(
    vault: Path,
    relative_path: str,
    *,
    complete: bool = True,
    errors: tuple[str, ...] = (),
) -> ObsidianRawSourceSnapshot:
    """Build one raw observation from a source fixture."""
    path = vault / relative_path
    raw_bytes = path.read_bytes()
    return ObsidianRawSourceSnapshot(
        files=(
            ObsidianRawSourceFile(
                relative_path=relative_path,
                raw_text=raw_bytes.decode("utf-8"),
            ),
        ),
        complete=complete,
        total_bytes_read=len(raw_bytes),
        errors=errors,
    )


def test_integrity_scans_managed_markdown_and_existing_index_errors(
    tmp_path: Path,
) -> None:
    """Known legacy encodings and unrecoverable redaction must be counted."""
    vault = tmp_path / "vault"
    relative_path = "Alexandria/Contexts/legacy.md"
    item = _managed_note(
        vault=vault,
        relative_path=relative_path,
        frontmatter=(
            "id: legacy\n"
            "alexandria_type: context\n"
            "title: Legacy\n"
            "tags: \"('alpha', 'beta')\"\n"
            "artifact_refs: scalar-ref\n"
            "evidence_refs:\n"
            "  - E-1\n"
            "linked_note_ids:\n"
            "conflict_set_ids: [C-1, 2]\n"
            'source_of_truth: "true"\n'
            "source: https://<REDACTED_LONG_VALUE>\n"
        ),
    )
    status = ObsidianVaultStatus(
        vault_path=str(vault),
        alexandria_root="Alexandria",
        vault_exists=True,
        alexandria_root_exists=True,
        indexed_notes=1,
        stale_notes=0,
        error_notes=1,
        index_errors=(
            ObsidianIndexError(
                note_path=relative_path,
                context_id="legacy",
                error_code=ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR,
                error_message="safe",
                detected_at=datetime.now(UTC),
            ),
        ),
    )
    service = _InventoryObsidianService(
        status,
        _raw_source_snapshot(vault, item),
    )

    snapshot = anyio.run(
        OperationalDataIntegrityService(service).snapshot,
        status,
    )

    assert snapshot.status is OperationalDataIntegrityStatus.DEGRADED
    assert snapshot.scanned_notes == 1
    assert {finding.code: finding.count for finding in snapshot.warnings} == {
        OperationalDataIntegrityWarningCode.LEGACY_TUPLE_COLLECTION: 1,
        OperationalDataIntegrityWarningCode.EMPTY_COLLECTION_SCALAR: 1,
        OperationalDataIntegrityWarningCode.INVALID_COLLECTION_TYPE: 2,
        OperationalDataIntegrityWarningCode.STRING_BOOLEAN: 1,
        OperationalDataIntegrityWarningCode.UNRECOVERABLE_REDACTED_URL: 1,
        OperationalDataIntegrityWarningCode.EXISTING_INDEX_ERRORS: 1,
    }
    assert all(finding.note_paths == (relative_path,) for finding in snapshot.warnings)


def test_integrity_warnings_do_not_change_operational_ready(
    tmp_path: Path,
) -> None:
    """Healthy infrastructure remains READY while integrity reports DEGRADED."""
    vault = tmp_path / "vault"
    relative_path = "Alexandria/Contexts/legacy.md"
    item = _managed_note(
        vault=vault,
        relative_path=relative_path,
        frontmatter=(
            'id: legacy\nalexandria_type: context\ntitle: Legacy\ntags: "()"\n'
        ),
    )
    status = ObsidianVaultStatus(
        vault_path=str(vault),
        alexandria_root="Alexandria",
        vault_exists=True,
        alexandria_root_exists=True,
        indexed_notes=1,
        stale_notes=0,
        error_notes=0,
    )
    obsidian = _InventoryObsidianService(
        status,
        _raw_source_snapshot(vault, item),
    )

    async def scenario() -> dict[str, object]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            snapshot = await OperationalReadinessService(
                database=database,
                context_service=_HealthyContextService(),
                obsidian_service=obsidian,
                graph_projection_service=HealthyGraphProjectionService(),
            ).snapshot()
            assert snapshot.status is OperationalReadinessStatus.READY
            assert snapshot.ready is True
            assert (
                overall_readiness_status(
                    replace(
                        snapshot,
                        data_integrity=unchecked_data_integrity_snapshot(),
                    )
                ).value
                == "READY_WITH_WARNINGS"
            )
            return OperationalReadinessSnapshotResponse.from_entity(
                snapshot
            ).model_dump(mode="json")
        finally:
            await database.shutdown()

    payload = anyio.run(scenario)

    assert payload["status"] == "READY"
    assert payload["overall_status"] == "READY_WITH_WARNINGS"
    assert payload["ready"] is True
    assert payload["warnings"] == []
    assert payload["data_integrity"] == {
        "status": "DEGRADED",
        "scanned_notes": 1,
        "warnings": [
            {
                "code": "LEGACY_TUPLE_COLLECTION",
                "count": 1,
                "note_paths": [relative_path],
                "fields": ["tags"],
            }
        ],
    }


def test_incomplete_inventory_is_degraded_even_without_error_samples(
    tmp_path: Path,
) -> None:
    """Error-sample saturation cannot make an incomplete scan appear healthy."""
    vault = tmp_path / "vault"
    vault.mkdir()
    status = ObsidianVaultStatus(
        vault_path=str(vault),
        alexandria_root="Alexandria",
        vault_exists=True,
        alexandria_root_exists=True,
        indexed_notes=0,
        stale_notes=0,
        error_notes=0,
    )
    obsidian = _InventoryObsidianService(
        status,
        ObsidianRawSourceSnapshot(
            files=(),
            complete=False,
            total_bytes_read=0,
            errors=(),
        ),
    )

    snapshot = anyio.run(
        OperationalDataIntegrityService(obsidian).snapshot,
        status,
    )

    assert snapshot.status is OperationalDataIntegrityStatus.DEGRADED
    assert snapshot.scanned_notes == 0
    assert len(snapshot.warnings) == 1
    assert snapshot.warnings[0].code is (
        OperationalDataIntegrityWarningCode.INVENTORY_SCAN_ERROR
    )


def test_integrity_scans_invalid_unindexed_raw_source_without_index_access(
    tmp_path: Path,
) -> None:
    """Malformed, unindexed YAML remains visible to lexical diagnostics."""
    vault = tmp_path / "vault"
    source_path = vault / "Alexandria" / "Contexts" / "unindexed.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("---\ntags: [unterminated\n", encoding="utf-8")
    inventory = ObsidianVaultInventoryService(
        ObsidianVaultConfigStore(
            default_vault_path=str(vault),
            default_alexandria_root="Alexandria",
            config_path=None,
        )
    )

    class _RawInventoryPort:
        async def raw_source_snapshot(self) -> ObsidianRawSourceSnapshot:
            return await inventory.raw_source_snapshot()

    status = ObsidianVaultStatus(
        vault_path=str(vault),
        alexandria_root="Alexandria",
        vault_exists=True,
        alexandria_root_exists=True,
        indexed_notes=0,
        stale_notes=0,
        error_notes=0,
    )

    snapshot = anyio.run(
        OperationalDataIntegrityService(_RawInventoryPort()).snapshot,
        status,
    )

    assert snapshot.status is OperationalDataIntegrityStatus.DEGRADED
    assert snapshot.scanned_notes == 1
    assert [(warning.code, warning.note_paths) for warning in snapshot.warnings] == [
        (
            OperationalDataIntegrityWarningCode.INVALID_COLLECTION_TYPE,
            ("Alexandria/Contexts/unindexed.md",),
        )
    ]


def test_integrity_diagnostics_are_off_loop_and_cancellation_owned(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Diagnostic CPU work stays responsive and completes before cancellation."""
    vault = tmp_path / "vault"
    vault.mkdir()
    status = ObsidianVaultStatus(
        vault_path=str(vault),
        alexandria_root="Alexandria",
        vault_exists=True,
        alexandria_root_exists=True,
        indexed_notes=0,
        stale_notes=0,
        error_notes=0,
    )
    source_snapshot = ObsidianRawSourceSnapshot(
        files=(
            ObsidianRawSourceFile(
                relative_path="Alexandria/Contexts/unindexed.md",
                raw_text="---\ntags: invalid-scalar\n",
            ),
        ),
        complete=True,
        total_bytes_read=24,
    )
    service = OperationalDataIntegrityService(
        _InventoryObsidianService(status, source_snapshot)
    )
    worker_started = asyncio.Event()
    worker_finished = Event()
    release_worker = Event()
    loop: asyncio.AbstractEventLoop | None = None
    original_scan = operational_data_integrity_service._scan_markdown

    def block_scan(
        markdown: str,
        note_path: str,
        findings: dict[
            OperationalDataIntegrityWarningCode,
            _WarningAccumulator,
        ],
    ) -> None:
        if loop is None:
            raise AssertionError("event loop must be captured before diagnostics")
        loop.call_soon_threadsafe(worker_started.set)
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test did not release integrity diagnostics")
        try:
            original_scan(markdown, note_path, findings)
        finally:
            worker_finished.set()

    monkeypatch.setattr(
        operational_data_integrity_service,
        "_scan_markdown",
        block_scan,
    )

    async def scenario() -> None:
        nonlocal loop
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(service.snapshot(status))
        try:
            async with asyncio.timeout(2):
                await worker_started.wait()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker_finished.is_set()

    anyio.run(scenario)
