"""Safe vault-relative path policy for Obsidian Memory Compact notes."""

from __future__ import annotations

from pathlib import Path


def is_safe_note_id(compact_id: str) -> bool:
    """Return whether a compact id is safe for direct filename lookup.

    Args:
        compact_id: Memory Compact identifier.

    Returns:
        True when the identifier can be used as a local note filename.
    """
    if compact_id in {"", ".", ".."}:
        return False
    return (
        "/" not in compact_id
        and "\\" not in compact_id
        and ".." not in Path(compact_id).parts
    )


def resolve_base_dir(vault_path: str | Path, relative_dir: str | Path) -> Path:
    """Resolve the Memory Compact note directory inside an Obsidian vault.

    Args:
        vault_path: Obsidian vault root path.
        relative_dir: Memory Compact folder path relative to the vault.

    Returns:
        Absolute Memory Compact note directory path.

    Raises:
        ValueError: If `relative_dir` is absolute or traverses outside the vault.
    """
    vault = Path(vault_path).expanduser()
    if not vault.is_absolute():
        vault = Path.cwd() / vault
    relative = Path(relative_dir)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Memory Compact Obsidian directory must stay inside vault")
    return vault / relative
