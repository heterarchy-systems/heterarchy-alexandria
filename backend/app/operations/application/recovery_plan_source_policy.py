"""Canonical Vault source snapshot helpers for operational recovery planning."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from shutil import disk_usage
from typing import Protocol

from app.obsidian.infrastructure.markdown.paths import discover_managed_markdown_paths
from app.operations.domain.entities.recovery_plan import RecoverySourceSnapshot


class DiskUsageSnapshot(Protocol):
    """Filesystem capacity values required by recovery source planning."""

    @property
    def free(self) -> int:
        """Return free filesystem bytes.

        Returns:
            Available bytes on the inspected filesystem.
        """


class DiskUsageProvider(Protocol):
    """Callable boundary for filesystem capacity inspection."""

    def __call__(self, path: Path) -> DiskUsageSnapshot:
        """Return capacity values for one filesystem path."""


def _source_snapshot(
    *,
    vault_path: str,
    alexandria_root: str,
    disk_usage_provider: DiskUsageProvider = disk_usage,
) -> RecoverySourceSnapshot:
    """Capture bounded canonical Markdown evidence for recovery planning."""
    vault = Path(vault_path)
    root = vault / alexandria_root
    access_error: str | None = None
    try:
        markdown_files = discover_managed_markdown_paths(root) if root.exists() else []
    except OSError:
        markdown_files = []
        access_error = "source_snapshot_unreadable"
    representative = markdown_files[0] if markdown_files else None
    try:
        representative_hash = _file_sha256(representative) if representative else None
    except OSError:
        representative_hash = None
        access_error = "source_snapshot_unreadable"
    free_bytes = None
    if root.exists():
        try:
            free_bytes = disk_usage_provider(root).free
        except OSError:
            access_error = "source_snapshot_unreadable"
    return RecoverySourceSnapshot(
        vault_path=vault_path,
        alexandria_root=alexandria_root,
        managed_markdown_count=len(markdown_files),
        representative_path=None if representative is None else str(representative),
        representative_sha256=representative_hash,
        disk_free_bytes=free_bytes,
        access_error=access_error,
        markdown_manifest=_markdown_manifest(vault, markdown_files),
    )


def _markdown_manifest(vault: Path, markdown_files: list[Path]) -> dict[str, str]:
    """Return a metadata inventory without rereading every Markdown file."""
    return {
        str(path.relative_to(vault)): inventory_token
        for path in markdown_files
        if (inventory_token := _file_inventory_token(path)) is not None
    }


def _file_inventory_token(path: Path) -> str | None:
    """Return a cheap token that detects ordinary file writes."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
