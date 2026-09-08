"""Filesystem path helpers for Obsidian vault access."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from unicodedata import normalize

from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError

NOTE_SUFFIX = ".md"
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9가-힣._ -]+")


@dataclass(frozen=True, slots=True)
class ManagedMarkdownScan:
    """Bounded managed-Markdown discovery result."""

    paths: tuple[Path, ...]
    entries_seen: int
    total_bytes: int
    complete: bool
    errors: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize scan collections to immutable values."""
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "errors", tuple(self.errors))


def canonical_relative_path(relative_path: str | Path) -> str:
    """Return the OS-independent logical identity for a vault-relative path.

    Args:
        relative_path: Physical or client-supplied vault-relative path.

    Returns:
        POSIX-separated Unicode NFC path used by Alexandria read models.
    """
    return normalize("NFC", str(relative_path).replace("\\", "/"))


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


def scan_managed_markdown_paths(
    scan_root: Path,
    *,
    managed_root: Path | None = None,
    max_entries: int,
    max_files: int,
    max_total_bytes: int,
    max_file_bytes: int,
    max_errors: int,
) -> ManagedMarkdownScan:
    """Discover managed Markdown with explicit traversal and byte ceilings.

    The existing ``discover_managed_markdown_paths`` contract remains unchanged
    for maintenance callers. This scanner is the bounded source-read variant:
    it does not materialize an unbounded recursive path list and never follows
    a symlink directory.
    """
    if (
        min(
            max_entries,
            max_files,
            max_total_bytes,
            max_file_bytes,
            max_errors,
        )
        <= 0
    ):
        raise ValueError("bounded Markdown scan limits must be greater than zero")
    root = scan_root if managed_root is None else managed_root
    paths: list[Path] = []
    errors: list[str] = []
    entries_seen = 0
    total_bytes = 0
    complete = True
    pending: list[Path] = [scan_root]
    while pending:
        current = pending.pop()
        remaining_entries = max_entries - entries_seen
        if current.is_file() or current.is_symlink():
            entries = [current]
        else:
            try:
                entries = list(islice(current.iterdir(), remaining_entries + 1))
            except OSError:
                _append_bounded_scan_error(
                    errors, "SOURCE_DISCOVERY_FAILED", max_errors
                )
                complete = False
                continue
            if len(entries) > remaining_entries:
                _append_bounded_scan_error(
                    errors,
                    "SOURCE_SCAN_LIMIT_EXCEEDED",
                    max_errors,
                )
                return ManagedMarkdownScan(
                    paths=tuple(paths),
                    entries_seen=entries_seen + len(entries),
                    total_bytes=total_bytes,
                    complete=False,
                    errors=tuple(errors),
                )
            entries.sort(key=lambda path: str(path))
        for candidate in entries:
            entries_seen += 1
            if entries_seen > max_entries:
                _append_bounded_scan_error(
                    errors,
                    "SOURCE_SCAN_LIMIT_EXCEEDED",
                    max_errors,
                )
                complete = False
                return ManagedMarkdownScan(
                    paths=tuple(paths),
                    entries_seen=entries_seen,
                    total_bytes=total_bytes,
                    complete=False,
                    errors=tuple(errors),
                )
            if candidate.is_symlink() and candidate.is_dir():
                if _is_visible_directory(root, candidate):
                    _append_bounded_scan_error(
                        errors,
                        "PATH_SECURITY_VIOLATION",
                        max_errors,
                    )
                    complete = False
                continue
            if candidate.is_dir():
                if _is_visible_directory(root, candidate):
                    pending.append(candidate)
                continue
            if candidate.suffix != NOTE_SUFFIX or not _is_visible_managed_path(
                root,
                candidate,
            ):
                continue
            try:
                file_bytes = candidate.stat().st_size
            except OSError:
                _append_bounded_scan_error(errors, "SOURCE_READ_FAILED", max_errors)
                complete = False
                continue
            if (
                file_bytes > max_file_bytes
                or total_bytes + file_bytes > max_total_bytes
            ):
                _append_bounded_scan_error(
                    errors,
                    "SOURCE_SCAN_LIMIT_EXCEEDED",
                    max_errors,
                )
                complete = False
                return ManagedMarkdownScan(
                    paths=tuple(paths),
                    entries_seen=entries_seen,
                    total_bytes=total_bytes,
                    complete=False,
                    errors=tuple(errors),
                )
            if len(paths) >= max_files:
                _append_bounded_scan_error(
                    errors,
                    "SOURCE_SCAN_LIMIT_EXCEEDED",
                    max_errors,
                )
                complete = False
                return ManagedMarkdownScan(
                    paths=tuple(paths),
                    entries_seen=entries_seen,
                    total_bytes=total_bytes,
                    complete=False,
                    errors=tuple(errors),
                )
            paths.append(candidate)
            total_bytes += file_bytes
    paths.sort(key=lambda path: str(path))
    return ManagedMarkdownScan(
        paths=tuple(paths),
        entries_seen=entries_seen,
        total_bytes=total_bytes,
        complete=complete and not errors,
        errors=tuple(errors),
    )


def _append_bounded_scan_error(
    errors: list[str],
    error: str,
    max_errors: int,
) -> None:
    """Append one scan code without unbounded diagnostic growth."""
    if len(errors) < max_errors:
        errors.append(error)


def _is_visible_managed_path(managed_root: Path, candidate: Path) -> bool:
    """Return whether visible managed path.

    Args:
        managed_root: Managed root used by this operation.
        candidate: Candidate used by this operation.

    Returns:
        Whether visible managed path.
    """
    try:
        relative = candidate.relative_to(managed_root)
    except ValueError:
        return False
    return not any(part.startswith(".") for part in relative.parts[:-1])


def _is_visible_directory(managed_root: Path, candidate: Path) -> bool:
    """Return whether a discovered directory is inside visible managed state."""
    try:
        relative = candidate.relative_to(managed_root)
    except ValueError:
        return False
    return not any(part.startswith(".") for part in relative.parts)


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
    """Return whether symlink component.

    Args:
        root: Root used by this operation.
        candidate: Candidate used by this operation.

    Returns:
        Whether symlink component.
    """
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
