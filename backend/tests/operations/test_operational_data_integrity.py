"""Operational data-integrity diagnostics remain separate from readiness."""

from __future__ import annotations

import os

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import anyio
from app.memory.application.contexts.records.context_service_ports import (
    ContextReadinessPort,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianDataIntegrityPort,
    ObsidianReadinessPort,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.operations.application.readiness.operational_data_integrity_service import (
    OperationalDataIntegrityService,
)
from app.operations.application.readiness.operational_overall_readiness import (
    overall_readiness_status,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
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
        managed_paths: list[str],
    ) -> None:
        self._status = status
        self._managed_paths = managed_paths

    async def status(self) -> ObsidianVaultStatus:
        return self._status

    async def managed_markdown_paths(self) -> list[str]:
        return self._managed_paths


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
    service = _InventoryObsidianService(status, [item])

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
    obsidian = _InventoryObsidianService(status, [item])

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
