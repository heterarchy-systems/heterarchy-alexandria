"""Race-resistant atomic writes for canonical Markdown notes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_markdown(path: Path, content: str) -> None:
    """Write UTF-8 Markdown through a unique same-directory temporary file.

    Args:
        path: Final canonical Markdown path.
        content: Complete document text.
    """
    missing_parents: list[Path] = []
    parent = path.parent
    while not parent.exists():
        missing_parents.append(parent)
        parent = parent.parent
    for directory in reversed(missing_parents):
        directory.mkdir(exist_ok=True)
        _sync_directory(directory.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _sync_directory(path: Path) -> None:
    """Persist a canonical filename or newly created directory entry."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
