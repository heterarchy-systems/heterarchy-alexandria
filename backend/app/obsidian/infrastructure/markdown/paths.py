"""Filesystem path helpers for Obsidian vault access."""

from __future__ import annotations

import re
from pathlib import Path

from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError

NOTE_SUFFIX = ".md"
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9가-힣._ -]+")


def resolve_vault_path(vault_path: str | Path) -> Path:
    """Resolve an Obsidian vault root path.

    Args:
        vault_path: User or config supplied vault root.

    Returns:
        Absolute path for the vault root.
    """
    vault = Path(vault_path).expanduser()
    if not vault.is_absolute():
        vault = Path.cwd() / vault
    return vault.resolve()


def safe_relative_path(relative_path: str | Path) -> Path:
    """Validate a vault-relative path.

    Args:
        relative_path: Path supplied by an API/client.

    Returns:
        Safe relative Path.
    """
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ObsidianValidationError("Obsidian path must stay inside the vault")
    return relative


def resolve_note_path(vault_path: str | Path, relative_path: str | Path) -> Path:
    """Resolve one safe note path inside a vault.

    Args:
        vault_path: Vault root path.
        relative_path: Vault-relative note path.

    Returns:
        Absolute note path.
    """
    vault = resolve_vault_path(vault_path)
    relative = safe_relative_path(relative_path)
    target = (vault / relative).resolve()
    if vault not in target.parents and target != vault:
        raise ObsidianValidationError("Obsidian path escaped the vault")
    return target


def discover_managed_markdown_paths(
    scan_root: Path,
    *,
    managed_root: Path | None = None,
) -> list[Path]:
    """Discover managed Markdown while excluding vault-internal hidden directories.

    Obsidian metadata, trash, VCS data, and other dot-directories are operational
    filesystem state rather than Alexandria-managed notes.  When the configured
    Alexandria root is the vault root (``.``), those directories must not enter
    identity validation or recovery manifests.

    Args:
        scan_root: File or directory scope to enumerate.
        managed_root: Root used to decide whether a directory is hidden. Defaults
            to ``scan_root`` for whole-root scans.

    Returns:
        Sorted Markdown file candidates inside the managed identity domain.
    """
    root = scan_root if managed_root is None else managed_root
    discovered = (
        [scan_root]
        if scan_root.is_file()
        else sorted(scan_root.rglob(f"*{NOTE_SUFFIX}"))
    )
    return [
        path
        for path in discovered
        if path.is_file()
        and path.suffix == NOTE_SUFFIX
        and _is_visible_managed_path(root, path)
    ]


def _is_visible_managed_path(managed_root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(managed_root)
    except ValueError:
        return False
    return not any(part.startswith(".") for part in relative.parts[:-1])


def validate_discovered_note_path(
    vault_path: str | Path,
    managed_root: str | Path,
    candidate: Path,
) -> Path:
    """Reject symlinked or escaped Markdown files found during vault scans.

    Args:
        vault_path: Configured vault root.
        managed_root: Managed Alexandria root within the vault.
        candidate: Markdown path discovered by the filesystem scan.

    Returns:
        Canonical resolved candidate path inside both roots.

    Raises:
        ObsidianValidationError: If the candidate uses a symlink or escapes a root.
    """
    vault = resolve_vault_path(vault_path)
    root = resolve_note_path(vault, managed_root)
    if candidate.is_symlink() or _has_symlink_component(root, candidate):
        raise ObsidianValidationError(
            "PATH_SECURITY_VIOLATION: managed notes cannot use symlinks"
        )
    resolved = candidate.resolve(strict=True)
    if vault not in resolved.parents or root not in resolved.parents:
        raise ObsidianValidationError(
            "PATH_SECURITY_VIOLATION: managed note escaped the vault root"
        )
    return resolved


def _has_symlink_component(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def safe_filename(title: str) -> str:
    """Return a filesystem-friendly Markdown filename for a note title.

    Args:
        title: Human title.

    Returns:
        Safe filename ending with `.md`.
    """
    cleaned = _SAFE_FILENAME_PATTERN.sub("", title).strip(" .")
    filename = cleaned or "Untitled"
    if not filename.endswith(NOTE_SUFFIX):
        filename = f"{filename}{NOTE_SUFFIX}"
    return filename
