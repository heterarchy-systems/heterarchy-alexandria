"""Dry-run-first repair of legacy collection and Boolean metadata."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Final

from app.obsidian.application.notes.obsidian_note_templates import conversation_id
from app.obsidian.application.service.notes.obsidian_legacy_metadata_repair_support import (
    _apply_findings,
    _empty_plan,
    _plan_hash,
    _preflight_and_backup,
    _rollback_successful_repairs,
    _scan_frontmatter,
    _sha256,
)
from app.obsidian.domain.entities.obsidian_legacy_metadata_repair import (
    ObsidianLegacyMetadataRepairCandidate,
    ObsidianLegacyMetadataRepairPlan,
    ObsidianLegacyMetadataRepairReport,
    ObsidianLegacyMetadataRepairResult,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianReindexResult
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.obsidian.infrastructure.markdown.paths import (
    discover_managed_markdown_paths,
    resolve_note_path,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError

_REDACTED_URL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"https?://<REDACTED_LONG_VALUE>"
)


class ObsidianLegacyMetadataRepairService:
    """Scan and explicitly apply reversible legacy metadata repairs."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
    ) -> None:
        """Initialize ObsidianLegacyMetadataRepairService state and dependencies.

        Args:
            vault_config_store: Vault config store used by this operation.
            reindex: Reindex used by this operation.
        """
        self._vault_config_store = vault_config_store
        self._reindex = reindex

    async def plan(self) -> ObsidianLegacyMetadataRepairPlan:
        """Scan managed Markdown without changing source files.

        Returns:
            Source-hash-bound dry-run repair plan.
        """
        config = self._vault_config_store.current()
        root = resolve_note_path(config.vault_path, config.alexandria_root)
        if not root.exists():
            return _empty_plan()
        candidates: list[ObsidianLegacyMetadataRepairCandidate] = []
        scanned_documents = 0
        unrecoverable_redacted_urls = 0
        for discovered in discover_managed_markdown_paths(root):
            path = validate_discovered_note_path(
                config.vault_path,
                config.alexandria_root,
                discovered,
            )
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                continue
            scanned_documents += 1
            unrecoverable_redacted_urls += len(_REDACTED_URL_PATTERN.findall(text))
            findings = _scan_frontmatter(text)
            if not findings:
                continue
            candidates.append(
                ObsidianLegacyMetadataRepairCandidate(
                    note_path=str(path.relative_to(config.vault_path)),
                    original_sha256=_sha256(raw),
                    findings=findings,
                )
            )
        ordered = tuple(sorted(candidates, key=lambda item: item.note_path))
        repairable_fields = sum(
            finding.is_repairable
            for candidate in ordered
            for finding in candidate.findings
        )
        manual_review_fields = sum(
            not finding.is_repairable
            for candidate in ordered
            for finding in candidate.findings
        )
        return ObsidianLegacyMetadataRepairPlan(
            plan_hash=_plan_hash(
                candidates=ordered,
                scanned_documents=scanned_documents,
                unrecoverable_redacted_urls=unrecoverable_redacted_urls,
            ),
            dry_run=True,
            backup_required=True,
            scanned_documents=scanned_documents,
            affected_documents=len(ordered),
            repairable_fields=repairable_fields,
            manual_review_fields=manual_review_fields,
            unrecoverable_redacted_urls=unrecoverable_redacted_urls,
            candidates=ordered,
        )

    async def apply(
        self,
        expected_plan_hash: str,
    ) -> ObsidianLegacyMetadataRepairReport:
        """Apply only the unchanged, explicitly accepted repair plan.

        Args:
            expected_plan_hash: Hash of the dry-run plan accepted by the operator.

        Returns:
            Backup location and per-document repair evidence.
        """
        plan = await self.plan()
        if plan.plan_hash != expected_plan_hash:
            raise ObsidianValidationError("legacy metadata repair plan changed")
        repairable = tuple(
            candidate
            for candidate in plan.candidates
            if any(finding.is_repairable for finding in candidate.findings)
        )
        if not repairable:
            raise ObsidianValidationError(
                "legacy metadata repair plan has no repairable candidates"
            )
        config = self._vault_config_store.current()
        operation_root = (
            f".heterarchy-alexandria/legacy-metadata-repair/backups/{conversation_id()}"
        )
        originals = _preflight_and_backup(
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
            operation_root=operation_root,
            candidates=repairable,
        )
        results: list[ObsidianLegacyMetadataRepairResult] = []
        for candidate in repairable:
            path, raw = originals[candidate.note_path]
            try:
                updated = _apply_findings(
                    raw.decode("utf-8"),
                    tuple(
                        finding
                        for finding in candidate.findings
                        if finding.is_repairable
                    ),
                )
                atomic_write_markdown(path, updated)
                after = path.read_bytes()
                results.append(
                    ObsidianLegacyMetadataRepairResult(
                        note_path=candidate.note_path,
                        before_sha256=candidate.original_sha256,
                        after_sha256=_sha256(after),
                        success=True,
                        failure_reason=None,
                    )
                )
            except (OSError, UnicodeError, ValueError) as exc:
                atomic_write_markdown(path, raw.decode("utf-8"))
                results.append(
                    ObsidianLegacyMetadataRepairResult(
                        note_path=candidate.note_path,
                        before_sha256=candidate.original_sha256,
                        after_sha256=candidate.original_sha256,
                        success=False,
                        failure_reason=exc.__class__.__name__,
                    )
                )
        applied_count = sum(item.success for item in results)
        failed_count = len(results) - applied_count
        if applied_count:
            try:
                await self._reindex()
            except Exception:
                _rollback_successful_repairs(
                    originals=originals,
                    results=results,
                )
                raise
        return ObsidianLegacyMetadataRepairReport(
            status="succeeded" if failed_count == 0 else "partial",
            plan_hash=plan.plan_hash,
            backup_root=operation_root,
            applied_count=applied_count,
            failed_count=failed_count,
            unrecoverable_redacted_urls=plan.unrecoverable_redacted_urls,
            results=tuple(results),
        )
