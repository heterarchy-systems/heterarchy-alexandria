"""No-follow regular-file access and bounded digest streaming."""

from __future__ import annotations

import hashlib
import os
import stat

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    CHUNK_SIZE,
    AssetDigest,
    AssetMetadata,
    CachedAsset,
    FileSignature,
    SinkProtocol,
    cache_error,
    validate_cached_blob_name,
)
from app.memory.infrastructure.providers.artifact_cache.directory_access import (
    stat_child,
    validate_component,
)

_READ_LEAF_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def open_regular_leaf(
    parent_fd: int,
    name: str,
    *,
    expected: FileSignature | None = None,
) -> tuple[int, FileSignature]:
    """Open a regular no-follow leaf and compare descriptor-relative evidence.

    Args:
        parent_fd: Open descriptor for the trusted parent directory.
        name: Single leaf component relative to the parent descriptor.
        expected: Optional signature captured during a prior inspection.

    Returns:
        The opened file descriptor and signature captured from that descriptor.
    """
    validate_component(name)
    before = stat_child(parent_fd, name)
    if before is None or not stat.S_ISREG(before.st_mode):
        cache_error("cache asset is not a regular file")
    before_signature = FileSignature.from_stat(before)
    if expected is not None and before_signature != expected:
        cache_error("cache asset changed during access")
    descriptor = os.open(name, _READ_LEAF_FLAGS, dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        after = stat_child(parent_fd, name)
        if (
            after is None
            or not stat.S_ISREG(opened.st_mode)
            or before_signature != FileSignature.from_stat(opened)
            or FileSignature.from_stat(opened) != FileSignature.from_stat(after)
        ):
            cache_error("cache asset changed during access")
        return descriptor, FileSignature.from_stat(opened)
    except BaseException:
        os.close(descriptor)
        raise


def read_regular_leaf(
    parent_fd: int,
    name: str,
    *,
    expected: FileSignature | None = None,
) -> tuple[bytes, FileSignature]:
    """Read one regular file and reject leaf changes around the read.

    Args:
        parent_fd: Open descriptor for the trusted parent directory.
        name: Single leaf component relative to the parent descriptor.
        expected: Optional signature captured during a prior inspection.

    Returns:
        The file bytes and signature validated around the complete read.
    """
    descriptor, signature = open_regular_leaf(parent_fd, name, expected=expected)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read()
        opened_after = os.fstat(descriptor)
        entry_after = stat_child(parent_fd, name)
        if (
            FileSignature.from_stat(opened_after) != signature
            or entry_after is None
            or FileSignature.from_stat(entry_after) != signature
        ):
            cache_error("cache asset changed during read")
        return content, signature
    finally:
        os.close(descriptor)


def validate_asset_digest(
    asset: CachedAsset,
    digest: AssetDigest,
    metadata: AssetMetadata | None,
) -> None:
    """Check declared length and all available immutable identities.

    Args:
        asset: Captured cache entry whose blob name may encode an identity.
        digest: Incrementally calculated content identities.
        metadata: Optional remote identity requirements for this asset.
    """
    if metadata is not None:
        if digest.size != metadata.size:
            cache_error("conflicting cached asset length")
        expected_blob = metadata.lfs_sha256 or metadata.git_blob_sha1
        if (
            asset.blob_name is not None
            and expected_blob is not None
            and asset.blob_name != expected_blob
        ):
            cache_error("conflicting cached asset")
        if metadata.lfs_sha256 is not None and digest.sha256 != metadata.lfs_sha256:
            cache_error("conflicting cached asset identity")
        if (
            metadata.git_blob_sha1 is not None
            and digest.git_blob_sha1 != metadata.git_blob_sha1
        ):
            cache_error("conflicting cached asset identity")
        if (
            metadata.lfs_sha256 is None
            and metadata.git_blob_sha1 is None
            and asset.blob_name is not None
        ):
            validate_cached_blob_name(asset.blob_name, digest)
    elif asset.blob_name is not None:
        validate_cached_blob_name(asset.blob_name, digest)


def asset_hash_requirements(
    asset: CachedAsset,
    metadata: AssetMetadata | None,
) -> tuple[bool, bool]:
    """Select only the raw/LFS or Git identities required for one asset.

    Args:
        asset: Captured cache entry whose blob name may encode an identity.
        metadata: Optional remote identity requirements for this asset.

    Returns:
        Whether to compute raw SHA-256 and Git blob SHA-1, respectively.
    """
    need_sha256 = metadata is not None and metadata.lfs_sha256 is not None
    need_git_sha1 = metadata is not None and metadata.git_blob_sha1 is not None
    if not need_sha256 and not need_git_sha1 and asset.blob_name is not None:
        need_sha256 = len(asset.blob_name) == 64
        need_git_sha1 = len(asset.blob_name) == 40
    return need_sha256, need_git_sha1


def stream_regular_leaf(
    parent_fd: int,
    name: str,
    *,
    expected: FileSignature,
    asset_name: str,
    sink: SinkProtocol | None,
    need_sha256: bool,
    need_git_sha1: bool,
    expected_size: int | None = None,
) -> AssetDigest:
    """Stream one captured regular file in fixed chunks and validate its evidence.

    Args:
        parent_fd: Open descriptor for the trusted parent directory.
        name: Single leaf component relative to the parent descriptor.
        expected: Signature captured during asset inspection.
        asset_name: Fixed logical asset name supplied to the receiver.
        sink: Optional caller-owned bounded streaming receiver.
        need_sha256: Compute the raw-content SHA-256 digest when true.
        need_git_sha1: Compute the Git blob SHA-1 identity when true.
        expected_size: Optional length required by remote metadata.

    Returns:
        The length and requested digests validated against file evidence.
    """
    descriptor, signature = open_regular_leaf(parent_fd, name, expected=expected)
    try:
        before = os.fstat(descriptor)
        size = before.st_size
        if size < 1:
            cache_error("cached asset length is invalid")
        if expected_size is not None and size != expected_size:
            cache_error("conflicting cached asset length")
        if sink is not None:
            sink.begin_asset(asset_name, size)
        raw_sha256 = hashlib.sha256() if need_sha256 else None
        git_sha1 = hashlib.sha1() if need_git_sha1 else None
        if git_sha1 is not None:
            git_sha1.update(f"blob {size}\0".encode("ascii"))
        remaining = size
        while remaining:
            chunk = os.read(descriptor, min(CHUNK_SIZE, remaining))
            if not chunk:
                cache_error("cached asset shortened during read")
            remaining -= len(chunk)
            if raw_sha256 is not None:
                raw_sha256.update(chunk)
            if git_sha1 is not None:
                git_sha1.update(chunk)
            if sink is not None:
                sink.write_chunk(chunk)
        if os.read(descriptor, 1):
            cache_error("cached asset grew during read")
        after = os.fstat(descriptor)
        entry = stat_child(parent_fd, name)
        if (
            FileSignature.from_stat(after) != signature
            or entry is None
            or FileSignature.from_stat(entry) != signature
        ):
            cache_error("cached asset changed during read")
        return AssetDigest(
            size,
            raw_sha256.hexdigest() if raw_sha256 is not None else None,
            git_sha1.hexdigest() if git_sha1 is not None else None,
        )
    finally:
        os.close(descriptor)
