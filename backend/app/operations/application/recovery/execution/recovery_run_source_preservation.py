"""Source snapshot, preservation, and quarantine operations for recovery."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from shutil import disk_usage

from app.obsidian.infrastructure.markdown.paths import discover_managed_markdown_paths
from app.operations.domain.entities.recovery_plan import (
    RecoveryPlan,
    RecoverySourceSnapshot,
)
from app.shared.types.extra_types import JSONObject


async def _snapshot_sources(plan: RecoveryPlan) -> JSONObject:
    """Execute snapshot sources.

    Args:
        plan: Plan used by this operation.

    Returns:
        JSONObject result produced by snapshot sources.
    """
    return {
        "managed_markdown_count": plan.source_snapshot.managed_markdown_count,
        "representative_path": plan.source_snapshot.representative_path,
        "representative_sha256": plan.source_snapshot.representative_sha256,
        "markdown_manifest_count": len(plan.source_snapshot.markdown_manifest),
    }


def _source_snapshot_from_vault(
    vault_path: str,
    alexandria_root: str,
) -> RecoverySourceSnapshot:
    """Execute source snapshot from vault.

    Args:
        vault_path: Vault path used by this operation.
        alexandria_root: Alexandria root used by this operation.

    Returns:
        RecoverySourceSnapshot result produced by source snapshot from vault.
    """
    vault = Path(vault_path)
    root = Path(vault_path) / alexandria_root
    markdown_files = discover_managed_markdown_paths(root) if root.exists() else []
    representative = markdown_files[0] if markdown_files else None
    return RecoverySourceSnapshot(
        vault_path=vault_path,
        alexandria_root=alexandria_root,
        managed_markdown_count=len(markdown_files),
        representative_path=None if representative is None else str(representative),
        representative_sha256=_file_sha256(representative),
        disk_free_bytes=disk_usage(root).free if root.exists() else None,
        access_error=None,
        markdown_manifest=_markdown_manifest(vault, markdown_files),
    )


def _source_preservation_result(snapshot: RecoverySourceSnapshot) -> JSONObject:
    """Execute source preservation result.

    Args:
        snapshot: Snapshot used by this operation.

    Returns:
        JSONObject result produced by source preservation result.
    """
    current_manifest = _current_markdown_manifest(snapshot)
    before_paths = set(snapshot.markdown_manifest)
    after_paths = set(current_manifest)
    removed_paths = sorted(before_paths - after_paths)
    added_paths = sorted(after_paths - before_paths)
    changed_paths = sorted(
        path
        for path in before_paths & after_paths
        if snapshot.markdown_manifest[path] != current_manifest[path]
    )
    return {
        "preserved": not removed_paths and not added_paths and not changed_paths,
        "managed_markdown_count": len(snapshot.markdown_manifest),
        "removed_count": len(removed_paths),
        "changed_count": len(changed_paths),
        "added_count": len(added_paths),
        "removed_paths": removed_paths,
        "changed_paths": changed_paths,
        "added_paths": added_paths,
    }


def _current_markdown_manifest(snapshot: RecoverySourceSnapshot) -> dict[str, str]:
    """Execute current markdown manifest.

    Args:
        snapshot: Snapshot used by this operation.

    Returns:
        dict[str, str] result produced by current markdown manifest.
    """
    vault = Path(snapshot.vault_path)
    root = vault / snapshot.alexandria_root
    markdown_files = discover_managed_markdown_paths(root) if root.exists() else []
    return _markdown_manifest(vault, markdown_files)


def _markdown_manifest(vault: Path, markdown_files: list[Path]) -> dict[str, str]:
    """Execute markdown manifest.

    Args:
        vault: Vault used by this operation.
        markdown_files: Markdown files used by this operation.

    Returns:
        dict[str, str] result produced by markdown manifest.
    """
    return {
        str(path.relative_to(vault)): inventory_token
        for path in markdown_files
        if (inventory_token := _file_inventory_token(path)) is not None
    }


def _file_inventory_token(path: Path) -> str | None:
    """Execute file inventory token.

    Args:
        path: Path used by this operation.

    Returns:
        str | None result produced by file inventory token.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _file_sha256(path: Path | None) -> str | None:
    """Execute file sha256.

    Args:
        path: Path used by this operation.

    Returns:
        str | None result produced by file sha256.
    """
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
