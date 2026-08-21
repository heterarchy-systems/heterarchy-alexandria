"""Hash-locked, backup-first repair of known legacy Obsidian index errors."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

from app.obsidian.application.notes.obsidian_note_templates import conversation_id
from app.obsidian.domain.entities.obsidian_index_error_repair import (
    ObsidianIndexErrorRepairCandidate,
    ObsidianIndexErrorRepairPlan,
    ObsidianIndexErrorRepairReport,
    ObsidianIndexErrorRepairSkip,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexErrorCode,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
    update_frontmatter_scalars,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.serialization.orjson_codec import (
    dumps_canonical_json,
    dumps_pretty_json,
)
from app.shared.types.extra_types import JSONObject

_LEGACY_ARCHIVED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "saved",
        "saved_with_warnings",
        "redacted_and_saved",
        "succeeded",
        "succeeded_with_warnings",
    }
)
_INDEX_ROOTS: Final[frozenset[str]] = frozenset(
    {"Compiled", "Runs", "Schemas", "Sources", "Wiki"}
)


class ObsidianIndexErrorRepairService:
    """Plan and apply narrow, reversible frontmatter repairs."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
        status: Callable[[], Awaitable[ObsidianVaultStatus]],
    ) -> None:
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._reindex = reindex
        self._status = status

    async def plan(self) -> ObsidianIndexErrorRepairPlan:
        """Return a source-hash-bound repair plan without mutating Markdown.

        Returns:
            Dry-run repair plan for known legacy errors.
        """
        config = self._vault_config_store.current()
        candidates: list[ObsidianIndexErrorRepairCandidate] = []
        skipped: list[ObsidianIndexErrorRepairSkip] = []
        for error in await self._repository.list_index_errors(limit=1000):
            try:
                path = validate_discovered_note_path(
                    config.vault_path,
                    config.alexandria_root,
                    resolve_note_path(config.vault_path, error.note_path),
                )
                raw = path.read_bytes()
                text = raw.decode("utf-8")
                frontmatter = frontmatter_json(
                    parse_markdown_document(text).frontmatter
                )
                replacements, reason = _legacy_replacements(
                    note_path=error.note_path,
                    error_code=error.error_code,
                    frontmatter=frontmatter,
                )
            except (OSError, UnicodeError, ValueError, ObsidianValidationError) as exc:
                skipped.append(
                    ObsidianIndexErrorRepairSkip(
                        note_path=error.note_path,
                        error_code=error.error_code,
                        reason=f"manual_review:{exc.__class__.__name__}",
                    )
                )
                continue
            if not replacements:
                skipped.append(
                    ObsidianIndexErrorRepairSkip(
                        note_path=error.note_path,
                        error_code=error.error_code,
                        reason=reason,
                    )
                )
                continue
            candidates.append(
                ObsidianIndexErrorRepairCandidate(
                    note_path=error.note_path,
                    error_code=error.error_code,
                    original_sha256=_sha256(raw),
                    replacements=tuple(sorted(replacements.items())),
                    reason=reason,
                )
            )
        ordered_candidates = tuple(sorted(candidates, key=lambda item: item.note_path))
        ordered_skipped = tuple(sorted(skipped, key=lambda item: item.note_path))
        return ObsidianIndexErrorRepairPlan(
            plan_hash=_plan_hash(ordered_candidates, ordered_skipped),
            dry_run=True,
            backup_required=True,
            candidates=ordered_candidates,
            skipped=ordered_skipped,
        )

    async def apply(
        self,
        expected_plan_hash: str,
    ) -> ObsidianIndexErrorRepairReport:
        """Apply an unchanged plan after preserving every original file.

        Args:
            expected_plan_hash: Hash returned by the inspected plan.

        Returns:
            Backup and residual-error evidence for the applied plan.
        """
        plan = await self.plan()
        if not plan.candidates:
            raise ObsidianValidationError("index error repair plan has no candidates")
        if plan.skipped:
            raise ObsidianValidationError(
                "index error repair plan contains manual-review items"
            )
        if plan.plan_hash != expected_plan_hash:
            raise ObsidianValidationError("index error repair plan changed")
        config = self._vault_config_store.current()
        run_id = conversation_id()
        operation_root = f".heterarchy-alexandria/index-error-repair/backups/{run_id}"
        report_stem = f".heterarchy-alexandria/index-error-repair/reports/index-error-repair-{run_id}"
        markdown_report = f"{report_stem}.md.txt"
        json_report = f"{report_stem}.json"
        originals = _preflight_paths(
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
            operation_root=operation_root,
            markdown_report=markdown_report,
            json_report=json_report,
            candidates=plan.candidates,
        )
        _write_backups(
            vault_path=config.vault_path,
            operation_root=operation_root,
            originals=originals,
        )
        patched: list[Path] = []
        try:
            for candidate in plan.candidates:
                path, raw = originals[candidate.note_path]
                if _sha256(raw) != candidate.original_sha256:
                    raise ObsidianValidationError(
                        f"index repair source changed: {candidate.note_path}"
                    )
                updated = update_frontmatter_scalars(
                    raw.decode("utf-8"),
                    dict(candidate.replacements),
                )
                atomic_write_markdown(path, updated)
                patched.append(path)
        except (OSError, UnicodeError, ValueError, ObsidianValidationError):
            for path in patched:
                raw = next(item[1] for item in originals.values() if item[0] == path)
                atomic_write_markdown(path, raw.decode("utf-8"))
            raise
        await self._reindex()
        final_status = await self._status()
        residual_paths = tuple(error.note_path for error in final_status.index_errors)
        report_status = "succeeded" if final_status.error_notes == 0 else "partial"
        _write_report(
            vault_path=config.vault_path,
            markdown_report=markdown_report,
            json_report=json_report,
            status=report_status,
            plan=plan,
            backup_root=operation_root,
            residual_error_notes=final_status.error_notes,
            residual_paths=residual_paths,
        )
        return ObsidianIndexErrorRepairReport(
            status=report_status,
            plan_hash=plan.plan_hash,
            applied_count=len(plan.candidates),
            backup_root=operation_root,
            report_markdown_path=markdown_report,
            report_json_path=json_report,
            residual_error_notes=final_status.error_notes,
            residual_error_paths=residual_paths,
        )


def _legacy_replacements(
    note_path: str,
    error_code: ObsidianIndexErrorCode,
    frontmatter: JSONObject,
) -> tuple[dict[str, str], str]:
    if error_code is ObsidianIndexErrorCode.INVALID_STATUS:
        raw_status = frontmatter.get("status")
        normalized = (
            raw_status.strip().lower().replace("-", "_").replace(" ", "_")
            if isinstance(raw_status, str)
            else ""
        )
        if normalized in _LEGACY_ARCHIVED_STATUSES:
            return {"status": "archived"}, "legacy_terminal_status"
        return {}, "manual_review:unknown_status"
    if error_code is ObsidianIndexErrorCode.INVALID_SCOPE:
        project = frontmatter.get("project")
        replacements = {
            "scope": "PROJECT"
            if isinstance(project, str) and project.strip()
            else "GLOBAL"
        }
        if _is_index_note(note_path):
            replacements["status"] = "archived"
        return replacements, "legacy_scope_to_canonical_identity"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR:
        note_type = frontmatter.get("alexandria_type")
        note_id = frontmatter.get("id")
        if (
            note_type == AlexandriaNoteType.IMPLEMENTATION_HISTORY.value
            and not isinstance(note_id, str)
        ):
            suffix = hashlib.sha256(note_path.encode("utf-8")).hexdigest()[:24]
            return {"id": f"legacy-implementation-{suffix}"}, "missing_legacy_note_id"
    return {}, "manual_review:unsupported_error"


def _is_index_note(note_path: str) -> bool:
    path = Path(note_path)
    return (
        path.name.casefold() == "index.md"
        or path.name.casefold().startswith("00 ")
        or bool(path.parts and path.parts[0] in _INDEX_ROOTS)
    )


def _plan_hash(
    candidates: tuple[ObsidianIndexErrorRepairCandidate, ...],
    skipped: tuple[ObsidianIndexErrorRepairSkip, ...],
) -> str:
    payload: JSONObject = {
        "candidates": [
            {
                "note_path": item.note_path,
                "error_code": item.error_code.value,
                "original_sha256": item.original_sha256,
                "replacements": [
                    list(replacement) for replacement in item.replacements
                ],
                "reason": item.reason,
            }
            for item in candidates
        ],
        "skipped": [
            {
                "note_path": item.note_path,
                "error_code": item.error_code.value,
                "reason": item.reason,
            }
            for item in skipped
        ],
    }
    encoded = dumps_canonical_json(payload)
    return hashlib.sha256(encoded).hexdigest()


def _preflight_paths(
    vault_path: Path,
    alexandria_root: str,
    operation_root: str,
    markdown_report: str,
    json_report: str,
    candidates: tuple[ObsidianIndexErrorRepairCandidate, ...],
) -> dict[str, tuple[Path, bytes]]:
    destinations = (
        resolve_note_path(vault_path, markdown_report),
        resolve_note_path(vault_path, json_report),
    )
    if any(path.exists() for path in destinations):
        raise ObsidianValidationError("index error repair report destination exists")
    originals: dict[str, tuple[Path, bytes]] = {}
    for candidate in candidates:
        source = validate_discovered_note_path(
            vault_path,
            alexandria_root,
            resolve_note_path(vault_path, candidate.note_path),
        )
        backup = resolve_note_path(
            vault_path,
            f"{operation_root}/{candidate.note_path}.original",
        )
        if backup.exists():
            raise ObsidianValidationError("index error repair backup exists")
        raw = source.read_bytes()
        if _sha256(raw) != candidate.original_sha256:
            raise ObsidianValidationError(
                f"index repair source changed: {candidate.note_path}"
            )
        originals[candidate.note_path] = (source, raw)
    return originals


def _write_backups(
    vault_path: Path,
    operation_root: str,
    originals: dict[str, tuple[Path, bytes]],
) -> None:
    for relative_path, (_, raw) in originals.items():
        backup = resolve_note_path(
            vault_path,
            f"{operation_root}/{relative_path}.original",
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
        if _sha256(backup.read_bytes()) != _sha256(raw):
            raise ObsidianValidationError(
                "index error repair backup verification failed"
            )


def _write_report(
    vault_path: Path,
    markdown_report: str,
    json_report: str,
    status: str,
    plan: ObsidianIndexErrorRepairPlan,
    backup_root: str,
    residual_error_notes: int,
    residual_paths: tuple[str, ...],
) -> None:
    markdown_path = resolve_note_path(vault_path, markdown_report)
    json_path = resolve_note_path(vault_path, json_report)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        "\n".join(
            [
                "# Obsidian Index Error Repair Report",
                "",
                f"- status: `{status}`",
                f"- plan_hash: `{plan.plan_hash}`",
                f"- applied_count: `{len(plan.candidates)}`",
                f"- backup_root: `{backup_root}`",
                f"- residual_error_notes: `{residual_error_notes}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    json_path.write_bytes(
        dumps_pretty_json(
            {
                "status": status,
                "plan_hash": plan.plan_hash,
                "applied_count": len(plan.candidates),
                "backup_root": backup_root,
                "residual_error_notes": residual_error_notes,
                "residual_error_paths": list(residual_paths),
            }
        )
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
