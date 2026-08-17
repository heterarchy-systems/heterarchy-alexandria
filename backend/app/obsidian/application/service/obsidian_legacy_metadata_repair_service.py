"""Dry-run-first repair of legacy collection and Boolean metadata."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Final

from app.obsidian.application.notes.frontmatter_metadata_normalization import (
    BOOLEAN_FIELDS,
    STRING_COLLECTION_FIELDS,
    normalize_boolean_metadata,
)
from app.obsidian.application.notes.obsidian_note_templates import conversation_id
from app.obsidian.domain.entities.obsidian_legacy_metadata_repair import (
    LegacyMetadataValue,
    ObsidianLegacyMetadataRepairCandidate,
    ObsidianLegacyMetadataRepairFinding,
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
        *,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
    ) -> None:
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
        *,
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


def _empty_plan() -> ObsidianLegacyMetadataRepairPlan:
    candidates: tuple[ObsidianLegacyMetadataRepairCandidate, ...] = ()
    return ObsidianLegacyMetadataRepairPlan(
        plan_hash=_plan_hash(
            candidates=candidates,
            scanned_documents=0,
            unrecoverable_redacted_urls=0,
        ),
        dry_run=True,
        backup_required=True,
        scanned_documents=0,
        affected_documents=0,
        repairable_fields=0,
        manual_review_fields=0,
        unrecoverable_redacted_urls=0,
        candidates=candidates,
    )


def _scan_frontmatter(
    text: str,
) -> tuple[ObsidianLegacyMetadataRepairFinding, ...]:
    lines, end_index = _frontmatter_lines(text)
    if end_index is None:
        return ()
    findings: list[ObsidianLegacyMetadataRepairFinding] = []
    for line_index, line in enumerate(lines[1:end_index], start=1):
        raw_line = line.rstrip("\r\n")
        if raw_line != raw_line.lstrip() or ":" not in raw_line:
            continue
        field_name, raw_value = raw_line.split(":", maxsplit=1)
        field_name = field_name.strip()
        current_value = raw_value.strip()
        scalar_value = _quoted_scalar(current_value)
        if field_name in STRING_COLLECTION_FIELDS:
            if not current_value:
                if not _has_block_list_items(
                    lines=lines,
                    start_index=line_index + 1,
                    end_index=end_index,
                ):
                    findings.append(
                        ObsidianLegacyMetadataRepairFinding(
                            field_name=field_name,
                            current_value=current_value,
                            proposed_value=(),
                            reason="empty_collection_scalar",
                            is_repairable=True,
                        )
                    )
                continue
            collection_value = (
                scalar_value
                if scalar_value is not None
                else _plain_legacy_collection_scalar(current_value)
            )
            if collection_value is not None:
                finding = _collection_finding(
                    field_name=field_name,
                    current_value=current_value,
                    scalar_value=collection_value,
                )
                if finding is not None:
                    findings.append(finding)
        elif field_name in BOOLEAN_FIELDS:
            boolean_value = scalar_value if scalar_value is not None else current_value
            try:
                normalized = normalize_boolean_metadata(boolean_value)
            except ValueError:
                findings.append(
                    ObsidianLegacyMetadataRepairFinding(
                        field_name=field_name,
                        current_value=current_value,
                        proposed_value=None,
                        reason="manual_review:invalid_boolean",
                        is_repairable=False,
                    )
                )
            else:
                if scalar_value is not None:
                    findings.append(
                        ObsidianLegacyMetadataRepairFinding(
                            field_name=field_name,
                            current_value=current_value,
                            proposed_value=normalized,
                            reason="string_boolean",
                            is_repairable=True,
                        )
                    )
    return tuple(findings)


def _collection_finding(
    *,
    field_name: str,
    current_value: str,
    scalar_value: str,
) -> ObsidianLegacyMetadataRepairFinding | None:
    stripped = scalar_value.strip()
    if not (
        (stripped.startswith("(") and stripped.endswith(")"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return None
    try:
        normalized = _normalize_legacy_string_collection(stripped)
    except ValueError:
        return ObsidianLegacyMetadataRepairFinding(
            field_name=field_name,
            current_value=current_value,
            proposed_value=None,
            reason="manual_review:invalid_collection_repr",
            is_repairable=False,
        )
    return ObsidianLegacyMetadataRepairFinding(
        field_name=field_name,
        current_value=current_value,
        proposed_value=normalized,
        reason="legacy_collection_repr",
        is_repairable=True,
    )


def _normalize_legacy_string_collection(value: str) -> tuple[str, ...]:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise ValueError("invalid legacy collection representation") from exc
    if not isinstance(parsed, list | tuple):
        raise ValueError("legacy collection must be a list or tuple")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            raise ValueError("legacy collection items must be strings")
        text = item.strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return tuple(normalized)


def _quoted_scalar(value: str) -> str | None:
    if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"'}:
        return None
    if value[0] == "'":
        return value[1:-1].replace("''", "'")
    return value[1:-1]


def _plain_legacy_collection_scalar(value: str) -> str | None:
    stripped = value.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped
    return None


def _has_block_list_items(
    *,
    lines: Sequence[str],
    start_index: int,
    end_index: int,
) -> bool:
    for line in lines[start_index:end_index]:
        if line == line.lstrip() and line.strip():
            return False
        if line.strip().startswith("-"):
            return True
    return False


def _apply_findings(
    text: str,
    findings: tuple[ObsidianLegacyMetadataRepairFinding, ...],
) -> str:
    lines, end_index = _frontmatter_lines(text)
    if end_index is None:
        raise ValueError("FRONTMATTER_PARSE_ERROR: frontmatter is required")
    finding_by_field = {item.field_name: item for item in findings}
    output: list[str] = [lines[0]]
    replaced_fields: set[str] = set()
    for line in lines[1:end_index]:
        raw_line = line.rstrip("\r\n")
        field_name = (
            raw_line.split(":", maxsplit=1)[0].strip()
            if raw_line == raw_line.lstrip() and ":" in raw_line
            else ""
        )
        finding = finding_by_field.get(field_name)
        if finding is None:
            output.append(line)
            continue
        line_ending = line[len(raw_line) :] or "\n"
        output.extend(
            _render_replacement(
                field_name=field_name,
                value=finding.proposed_value,
                line_ending=line_ending,
            )
        )
        replaced_fields.add(field_name)
    if replaced_fields != set(finding_by_field):
        raise ValueError("legacy metadata repair target changed")
    output.extend(lines[end_index:])
    return "".join(output)


def _render_replacement(
    *,
    field_name: str,
    value: LegacyMetadataValue,
    line_ending: str,
) -> list[str]:
    if isinstance(value, tuple):
        if not value:
            return [f"{field_name}: []{line_ending}"]
        return [
            f"{field_name}:{line_ending}",
            *[f"  - {_yaml_string(item)}{line_ending}" for item in value],
        ]
    if isinstance(value, bool):
        return [f"{field_name}: {'true' if value else 'false'}{line_ending}"]
    raise ValueError("legacy metadata repair has no proposed value")


def _yaml_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _frontmatter_lines(text: str) -> tuple[list[str], int | None]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n").strip() != "---":
        return lines, None
    end_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n").strip() == "---"
        ),
        None,
    )
    return lines, end_index


def _plan_hash(
    *,
    candidates: tuple[ObsidianLegacyMetadataRepairCandidate, ...],
    scanned_documents: int,
    unrecoverable_redacted_urls: int,
) -> str:
    payload = {
        "scanned_documents": scanned_documents,
        "unrecoverable_redacted_urls": unrecoverable_redacted_urls,
        "candidates": [
            {
                "note_path": candidate.note_path,
                "original_sha256": candidate.original_sha256,
                "findings": [
                    {
                        "field_name": finding.field_name,
                        "current_value": finding.current_value,
                        "proposed_value": finding.proposed_value,
                        "reason": finding.reason,
                        "is_repairable": finding.is_repairable,
                    }
                    for finding in candidate.findings
                ],
            }
            for candidate in candidates
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256(encoded)


def _preflight_and_backup(
    *,
    vault_path: Path,
    alexandria_root: str,
    operation_root: str,
    candidates: Sequence[ObsidianLegacyMetadataRepairCandidate],
) -> dict[str, tuple[Path, bytes]]:
    originals: dict[str, tuple[Path, bytes]] = {}
    for candidate in candidates:
        path = validate_discovered_note_path(
            vault_path,
            alexandria_root,
            resolve_note_path(vault_path, candidate.note_path),
        )
        raw = path.read_bytes()
        if _sha256(raw) != candidate.original_sha256:
            raise ObsidianValidationError(
                f"legacy metadata repair source changed: {candidate.note_path}"
            )
        backup = resolve_note_path(
            vault_path,
            f"{operation_root}/{candidate.note_path}.original",
        )
        if backup.exists():
            raise ObsidianValidationError("legacy metadata repair backup exists")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
        if backup.read_bytes() != raw:
            raise ObsidianValidationError(
                "legacy metadata repair backup verification failed"
            )
        originals[candidate.note_path] = (path, raw)
    return originals


def _rollback_successful_repairs(
    *,
    originals: dict[str, tuple[Path, bytes]],
    results: Sequence[ObsidianLegacyMetadataRepairResult],
) -> None:
    """Restore originals if the required post-apply reindex fails."""
    for result in results:
        if not result.success:
            continue
        path, raw = originals[result.note_path]
        atomic_write_markdown(path, raw.decode("utf-8"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
