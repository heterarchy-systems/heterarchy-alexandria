"""Vault move report path resolution and rendering."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.obsidian.application.notes.obsidian_note_templates import (
    LIBRARIAN_OPERATIONS_FOLDER,
    conversation_id,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianVaultMoveApplyRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianVaultMoveApplied,
    ObsidianVaultMoveSkip,
    ObsidianVaultMoveVerification,
)
from app.obsidian.infrastructure.markdown.paths import resolve_note_path
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject


def vault_move_report_paths(
    vault_path: Path,
    alexandria_root: str,
    request: ObsidianVaultMoveApplyRequest,
) -> tuple[str, str, Path, Path]:
    base_path = request.report_path or (
        f"{alexandria_root}/{LIBRARIAN_OPERATIONS_FOLDER}/Reports/"
        f"vault-move-{conversation_id()}"
    )
    report_stem = base_path.removesuffix(".md").removesuffix(".json")
    markdown_relative = f"{report_stem}.md"
    json_relative = f"{report_stem}.json"
    markdown_path = resolve_note_path(vault_path, markdown_relative)
    json_path = resolve_note_path(vault_path, json_relative)
    return markdown_relative, json_relative, markdown_path, json_path


def ensure_vault_move_report_available(
    report_paths: tuple[str, str, Path, Path],
) -> None:
    _, _, markdown_path, json_path = report_paths
    if markdown_path.exists() or json_path.exists():
        raise ObsidianValidationError("vault move report destination exists")


def write_vault_move_report(
    report_paths: tuple[str, str, Path, Path],
    status: str,
    moved: Sequence[ObsidianVaultMoveApplied],
    skipped: Sequence[ObsidianVaultMoveSkip],
    verification: ObsidianVaultMoveVerification,
) -> tuple[str, str]:
    markdown_relative, json_relative, markdown_path, json_path = report_paths
    ensure_vault_move_report_available(report_paths)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        _vault_move_report_markdown(
            status=status,
            moved=moved,
            skipped=skipped,
            verification=verification,
        ),
        encoding="utf-8",
    )
    json_path.write_bytes(
        dumps_pretty_json(
            _vault_move_report_json(
                status=status,
                moved=moved,
                skipped=skipped,
                verification=verification,
            )
        )
    )
    return markdown_relative, json_relative


def _vault_move_report_json(
    status: str,
    moved: Sequence[ObsidianVaultMoveApplied],
    skipped: Sequence[ObsidianVaultMoveSkip],
    verification: ObsidianVaultMoveVerification,
) -> JSONObject:
    return {
        "status": status,
        "hard_delete_performed": False,
        "moved": [
            {
                "from": item.source_path,
                "to": item.destination_path,
                "reason": item.reason,
            }
            for item in moved
        ],
        "skipped": [
            {
                "from": item.source_path,
                "to": item.destination_path,
                "reason": item.reason,
            }
            for item in skipped
        ],
        "ambiguous": [],
        "verification": {
            "source_root_loose_notes_remaining": (
                verification.source_root_loose_notes_remaining
            ),
            "reindex_status": verification.reindex_status,
            "verification_hits": verification.verification_hits,
        },
    }


def _vault_move_report_markdown(
    status: str,
    moved: Sequence[ObsidianVaultMoveApplied],
    skipped: Sequence[ObsidianVaultMoveSkip],
    verification: ObsidianVaultMoveVerification,
) -> str:
    moved_lines = [
        f"- `{item.source_path}` -> `{item.destination_path}` — {item.reason}"
        for item in moved
    ] or ["- none"]
    skipped_lines = [
        f"- `{item.source_path}` -> `{item.destination_path}` — {item.reason}"
        for item in skipped
    ] or ["- none"]
    return "\n".join(
        [
            "# Librarian Vault Move Report",
            "",
            f"- status: `{status}`",
            "- hard_delete_performed: `false`",
            f"- reindex_status: `{verification.reindex_status}`",
            f"- verification_hits: `{verification.verification_hits}`",
            f"- source_root_loose_notes_remaining: `{verification.source_root_loose_notes_remaining}`",
            "",
            "## Moved",
            *moved_lines,
            "",
            "## Skipped",
            *skipped_lines,
            "",
        ]
    )
