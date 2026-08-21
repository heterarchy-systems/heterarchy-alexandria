"""Dry-run-first repair of legacy Obsidian metadata values."""

from __future__ import annotations

import os

from pathlib import Path

import anyio
import pytest
from app.obsidian.application.service.notes.obsidian_legacy_metadata_repair_service import (
    ObsidianLegacyMetadataRepairService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.entities.obsidian_note import ObsidianReindexResult
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url(path: Path) -> str:
    del path
    return os.environ["DATABASE_URL"]


def test_legacy_metadata_repair_is_dry_run_hash_locked_and_body_preserving(
    tmp_path: Path,
) -> None:
    """Apply must require a fresh plan, preserve body, and write exact backups."""

    async def scenario() -> tuple[object, ...]:
        vault = tmp_path / "vault"
        note_path = vault / "Alexandria/Contexts/Projects/Legacy Metadata.md"
        note_path.parent.mkdir(parents=True)
        body = (
            "# Legacy Metadata\n\n"
            "Public source: https://example.com/news/2026/07/29/article-123\n"
            "Lost source: https://<REDACTED_LONG_VALUE>\n"
        )
        original = (
            "---\n"
            "id: legacy_metadata\n"
            "alexandria_type: context\n"
            "title: Legacy Metadata\n"
            "scope: PROJECT\n"
            "project: heterarchy-alexandria\n"
            "status: active\n"
            "tags: \"(' alpha ', 'beta', 'alpha', '')\"\n"
            "artifact_refs:\n"
            "evidence_refs: \"['E-001', 'E-002']\"\n"
            "conflict_set_ids: ('C-001',)\n"
            'source_of_truth: "TrUe"\n'
            "---\n\n"
            f"{body}"
        )
        note_path.write_text(original, encoding="utf-8")
        database = Database(
            database_url=_database_url(tmp_path / "legacy-repair.db"),
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session=session),
            vault_path=str(vault),
            alexandria_root="Alexandria",
        )
        try:
            plan = await service.plan_legacy_metadata_repairs()
            dry_run_bytes = note_path.read_bytes()

            note_path.write_text(f"{original}\nDrift\n", encoding="utf-8")
            drift_rejected = False
            try:
                await service.apply_legacy_metadata_repairs(
                    expected_plan_hash=plan.plan_hash
                )
            except ObsidianValidationError:
                drift_rejected = True

            note_path.write_text(original, encoding="utf-8")
            current_plan = await service.plan_legacy_metadata_repairs()
            report = await service.apply_legacy_metadata_repairs(
                expected_plan_hash=current_plan.plan_hash
            )
            repaired = note_path.read_text(encoding="utf-8")
            backup = (
                vault
                / report.backup_root
                / "Alexandria/Contexts/Projects/Legacy Metadata.md.original"
            ).read_text(encoding="utf-8")
            return (
                plan,
                current_plan,
                report,
                dry_run_bytes,
                drift_rejected,
                repaired,
                backup,
                body,
            )
        finally:
            await session.close()
            await database.shutdown()

    (
        plan,
        current_plan,
        report,
        dry_run_bytes,
        drift_rejected,
        repaired,
        backup,
        body,
    ) = anyio.run(scenario)

    assert plan.dry_run is True
    assert plan.backup_required is True
    assert plan.scanned_documents == 1
    assert plan.affected_documents == 1
    assert plan.repairable_fields == 5
    assert plan.manual_review_fields == 0
    assert plan.unrecoverable_redacted_urls == 1
    assert dry_run_bytes == backup.encode()
    assert drift_rejected is True

    findings = {
        finding.field_name: finding for finding in current_plan.candidates[0].findings
    }
    assert findings["tags"].proposed_value == ("alpha", "beta")
    assert findings["artifact_refs"].proposed_value == ()
    assert findings["evidence_refs"].proposed_value == ("E-001", "E-002")
    assert findings["conflict_set_ids"].proposed_value == ("C-001",)
    assert findings["source_of_truth"].proposed_value is True

    assert report.status == "succeeded"
    assert report.applied_count == 1
    assert report.failed_count == 0
    assert report.unrecoverable_redacted_urls == 1
    assert report.results[0].success is True
    assert report.results[0].before_sha256 != report.results[0].after_sha256
    assert backup.startswith("---\nid: legacy_metadata\n")
    assert repaired.endswith(body)
    assert "id: legacy_metadata\n" in repaired
    assert "tags:\n  - 'alpha'\n  - 'beta'\n" in repaired
    assert "artifact_refs: []\n" in repaired
    assert "evidence_refs:\n  - 'E-001'\n  - 'E-002'\n" in repaired
    assert "conflict_set_ids:\n  - 'C-001'\n" in repaired
    assert "source_of_truth: true\n" in repaired
    assert "https://<REDACTED_LONG_VALUE>" in repaired


def test_legacy_metadata_repair_reports_unsafe_repr_for_manual_review(
    tmp_path: Path,
) -> None:
    """Nested or executable-looking collection reprs must never be evaluated."""

    async def scenario() -> tuple[object, ...]:
        vault = tmp_path / "vault"
        root = vault / "Alexandria/Notes"
        root.mkdir(parents=True)
        (root / "Nested.md").write_text(
            "---\n"
            "id: nested\n"
            "alexandria_type: note\n"
            "title: Nested\n"
            "status: active\n"
            "tags: \"(['nested'],)\"\n"
            "source_of_truth: GOAL.md\n"
            "---\n\nNested body.\n",
            encoding="utf-8",
        )
        (root / "Arbitrary.md").write_text(
            "---\n"
            "id: arbitrary\n"
            "alexandria_type: note\n"
            "title: Arbitrary\n"
            "status: active\n"
            "evidence_refs: \"(__import__('os'),)\"\n"
            "---\n\nArbitrary body.\n",
            encoding="utf-8",
        )
        database = Database(
            database_url=_database_url(tmp_path / "manual-review.db"),
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session=session),
            vault_path=str(vault),
            alexandria_root="Alexandria",
        )
        try:
            plan = await service.plan_legacy_metadata_repairs()
            apply_rejected = False
            try:
                await service.apply_legacy_metadata_repairs(
                    expected_plan_hash=plan.plan_hash
                )
            except ObsidianValidationError:
                apply_rejected = True
            return (
                plan,
                apply_rejected,
                (root / "Nested.md").read_text(encoding="utf-8"),
                (root / "Arbitrary.md").read_text(encoding="utf-8"),
            )
        finally:
            await session.close()
            await database.shutdown()

    plan, apply_rejected, nested, arbitrary = anyio.run(scenario)

    assert plan.affected_documents == 2
    assert plan.repairable_fields == 0
    assert plan.manual_review_fields == 3
    assert {
        finding.reason
        for candidate in plan.candidates
        for finding in candidate.findings
    } == {
        "manual_review:invalid_boolean",
        "manual_review:invalid_collection_repr",
    }
    assert apply_rejected is True
    assert "tags: \"(['nested'],)\"" in nested
    assert "source_of_truth: GOAL.md" in nested
    assert "evidence_refs: \"(__import__('os'),)\"" in arbitrary


def test_legacy_metadata_repair_rolls_back_when_reindex_fails(
    tmp_path: Path,
) -> None:
    """A failed required reindex must restore the backed-up source bytes."""

    async def fail_reindex() -> ObsidianReindexResult:
        raise RuntimeError("reindex failed")

    async def scenario() -> tuple[str, list[Path]]:
        vault = tmp_path / "vault"
        note_path = vault / "Alexandria/Notes/Rollback.md"
        note_path.parent.mkdir(parents=True)
        original = (
            "---\n"
            "id: rollback\n"
            "alexandria_type: note\n"
            "title: Rollback\n"
            "status: active\n"
            "tags: \"('alpha', 'beta')\"\n"
            "---\n\nBody must survive rollback.\n"
        )
        note_path.write_text(original, encoding="utf-8")
        service = ObsidianLegacyMetadataRepairService(
            vault_config_store=ObsidianVaultConfigStore(
                default_vault_path=str(vault),
                default_alexandria_root="Alexandria",
                config_path=None,
            ),
            reindex=fail_reindex,
        )
        plan = await service.plan()
        with pytest.raises(RuntimeError, match="reindex failed"):
            await service.apply(expected_plan_hash=plan.plan_hash)
        backups = list(
            (vault / ".heterarchy-alexandria/legacy-metadata-repair/backups").rglob(
                "Rollback.md.original"
            )
        )
        return note_path.read_text(encoding="utf-8"), backups

    restored, backups = anyio.run(scenario)

    assert "tags: \"('alpha', 'beta')\"" in restored
    assert restored.endswith("Body must survive rollback.\n")
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == restored
