"""Backup-first repair of narrowly recognized legacy Obsidian notes."""

from __future__ import annotations

import os
from pathlib import Path

import anyio

from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.models import (
    obsidian_index_models as _obsidian_index_models,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.infrastructure.database import Database

_OBSIDIAN_MODELS_LOADED = _obsidian_index_models


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def _write(path: Path, text: str) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


def test_legacy_index_error_repair_is_hash_locked_and_backup_first(
    tmp_path: Path,
) -> None:
    """Known repairs must preserve bytes, reject drift, and clear index errors."""

    async def scenario() -> tuple[
        int,
        tuple[str, ...],
        dict[str, bytes],
        dict[str, str],
        int,
        bool,
        bool,
    ]:
        vault = tmp_path / "vault"
        root = vault / "Alexandria"
        sources = {
            "Alexandria/Contexts/Projects/Legacy Saved.md": _write(
                root / "Contexts/Projects/Legacy Saved.md",
                "---\n"
                "id: legacy_saved\n"
                "alexandria_type: context\n"
                "title: Legacy Saved\n"
                "scope: PROJECT\n"
                "project: heterarchy-alexandria\n"
                "status: saved\n"
                "---\n\n# Legacy Saved\n",
            ),
            "Alexandria/Contexts/Projects/00 Legacy Index.md": _write(
                root / "Contexts/Projects/00 Legacy Index.md",
                "---\n"
                "id: legacy_index\n"
                "alexandria_type: context\n"
                "title: Legacy Index\n"
                "scope: project-sources\n"
                "project: heterarchy-alexandria\n"
                "status: active\n"
                "---\n\n# Legacy Index\n",
            ),
            "Alexandria/Contexts/Projects/Invalid Content Hash.md": _write(
                root / "Contexts/Projects/Invalid Content Hash.md",
                "---\n"
                "id: invalid_content_hash\n"
                "alexandria_type: context\n"
                "title: Invalid Content Hash\n"
                "scope: PROJECT\n"
                "project: heterarchy-alexandria\n"
                "status: active\n"
                "content_hash: " + ("0" * 64) + "\n"
                "---\n\n# Invalid Content Hash\n\nCanonical body.\n",
            ),
            (
                "Alexandria/Contexts/Projects/heterarchy-alexandria/"
                "Implementation History/Legacy History.md"
            ): _write(
                root / "Contexts/Projects/heterarchy-alexandria/"
                "Implementation History/Legacy History.md",
                "---\n"
                "alexandria_type: implementation_history\n"
                "title: Legacy History\n"
                "project: heterarchy-alexandria\n"
                "status: active\n"
                "---\n\n# Legacy History\n",
            ),
        }
        database = Database(
            database_url=_database_url(),
            create_schema=True,
        )
        await database.initialize()
        session = database.session()
        service = ObsidianService(
            repository=SqlAlchemyObsidianIndexRepository(session=session),
            vault_path=str(vault),
            alexandria_root="Alexandria",
            context_reindex_manifest_validator=create_native_context_reindex_manifest_validator(),
        )
        try:
            initial = await service.reindex()
            plan = await service.plan_index_error_repairs()
            unchanged = all(
                (vault / path).read_bytes() == raw for path, raw in sources.items()
            )

            drift_path = vault / "Alexandria/Contexts/Projects/Legacy Saved.md"
            drift_path.write_text(
                drift_path.read_text(encoding="utf-8") + "\nDrift\n",
                encoding="utf-8",
            )
            drift_rejected = False
            try:
                await service.apply_index_error_repairs(
                    expected_plan_hash=plan.plan_hash
                )
            except ObsidianValidationError:
                drift_rejected = True

            current_sources = {path: (vault / path).read_bytes() for path in sources}
            current_plan = await service.plan_index_error_repairs()
            report = await service.apply_index_error_repairs(
                expected_plan_hash=current_plan.plan_hash
            )
            final_status = await service.status()
            second_reindex = await service.reindex()
            backup_matches = all(
                (vault / report.backup_root / f"{relative_path}.original").read_bytes()
                == raw
                for relative_path, raw in current_sources.items()
            )
            repaired = {
                "saved": drift_path.read_text(encoding="utf-8"),
                "index": (
                    vault / "Alexandria/Contexts/Projects/00 Legacy Index.md"
                ).read_text(encoding="utf-8"),
                "content_hash": (
                    vault / "Alexandria/Contexts/Projects/Invalid Content Hash.md"
                ).read_text(encoding="utf-8"),
                "history": (
                    vault / "Alexandria/Contexts/Projects/heterarchy-alexandria/"
                    "Implementation History/Legacy History.md"
                ).read_text(encoding="utf-8"),
            }
            reports_exist = (vault / report.report_markdown_path).is_file() and (
                vault / report.report_json_path
            ).is_file()
            return (
                initial.files_indexed,
                tuple(item.error_code.value for item in initial.error_details),
                sources,
                repaired,
                final_status.error_notes + len(second_reindex.error_details),
                unchanged and drift_rejected,
                backup_matches and reports_exist,
            )
        finally:
            await session.close()
            await database.shutdown()

    (
        files_indexed,
        error_codes,
        _sources,
        repaired,
        residual_errors,
        safety_checks,
        evidence_checks,
    ) = anyio.run(scenario)

    assert files_indexed == 0
    assert error_codes == (
        "INVALID_SCOPE",
        "INVALID_CONTENT_HASH",
        "INVALID_STATUS",
        "FRONTMATTER_PARSE_ERROR",
    )
    assert safety_checks is True
    assert evidence_checks is True
    assert residual_errors == 0
    assert "status: archived" in repaired["saved"]
    assert "scope: PROJECT" in repaired["index"]
    assert "status: archived" in repaired["index"]
    expected_content_hash = context_content_hash(
        "# Invalid Content Hash\n\nCanonical body.\n"
    )
    assert f"content_hash: {expected_content_hash}" in repaired["content_hash"]
    assert "id: legacy-implementation-" in repaired["history"]
