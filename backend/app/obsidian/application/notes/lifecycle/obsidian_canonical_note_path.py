"""Canonical managed-root path resolution for bundle and identity workflows."""

from __future__ import annotations

from app.obsidian.infrastructure.markdown.paths import safe_relative_path


def canonical_managed_note_path(path: str, alexandria_root: str) -> str:
    """Return one safe vault-relative path rooted in the managed namespace.

    Args:
        path: Value supplied to canonical_managed_note_path.
        alexandria_root: Value supplied to canonical_managed_note_path.

    Returns:
        Result produced by canonical_managed_note_path.
    """
    safe_path = str(safe_relative_path(path))
    root = alexandria_root.strip().strip("/") or "."
    if root == "." or safe_path == root or safe_path.startswith(f"{root}/"):
        return safe_path
    return str(safe_relative_path(f"{root}/{safe_path}"))
