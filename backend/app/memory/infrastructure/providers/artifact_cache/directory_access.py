"""No-follow descriptor-relative directory access for artifact cache paths."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    FileSignature,
    cache_error,
)

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def stat_child(parent_fd: int, name: str) -> os.stat_result | None:
    """Stat one lexical child entry without following a symlink.

    Args:
        parent_fd: Open descriptor for the trusted parent directory.
        name: Single child component relative to the parent descriptor.

    Returns:
        The child metadata, or None when the entry is absent.
    """
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def validate_component(name: str) -> None:
    """Reject path syntax where one child component is required.

    Args:
        name: Candidate child component.
    """
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        cache_error("cache path component is invalid")


def open_child_directory(
    parent_fd: int,
    name: str,
    *,
    create: bool = False,
) -> tuple[int, FileSignature] | None:
    """Open one child directory without following or racing its entry.

    Args:
        parent_fd: Open descriptor for the trusted parent directory.
        name: Single child component relative to the parent descriptor.
        create: Create a private directory when the entry is absent.

    Returns:
        The opened descriptor and captured signature, or None when absent.
    """
    validate_component(name)
    before = stat_child(parent_fd, name)
    if before is None:
        if not create:
            return None
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        before = stat_child(parent_fd, name)
        if before is None:
            cache_error("cache directory changed during creation")
    if not stat.S_ISDIR(before.st_mode):
        cache_error("cache directory path is invalid")
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        after = stat_child(parent_fd, name)
        if (
            after is None
            or not stat.S_ISDIR(opened.st_mode)
            or not FileSignature.from_stat(before).same_directory_identity(
                FileSignature.from_stat(opened)
            )
            or not FileSignature.from_stat(opened).same_directory_identity(
                FileSignature.from_stat(after)
            )
        ):
            cache_error("cache directory changed during access")
        return descriptor, FileSignature.from_stat(opened)
    except BaseException:
        os.close(descriptor)
        raise


def open_root_directory(root: Path, *, create: bool) -> int | None:
    """Walk an absolute cache root one no-follow component at a time.

    Args:
        root: Absolute configured cache root path.
        create: Create missing path components with private permissions.

    Returns:
        The opened root descriptor, or None when a component is absent.
    """
    if not root.is_absolute():
        cache_error("configured cache root must be absolute")
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in root.parts[1:]:
            opened = open_child_directory(descriptor, component, create=create)
            if opened is None:
                os.close(descriptor)
                return None
            next_descriptor, _ = opened
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
