"""Typed contracts and lexical helpers for the embedding artifact cache."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import NoReturn, Protocol

from app.memory.infrastructure.providers.artifact_cache.artifact_enums import (
    ASSET_NAMES,
)

MODEL_CACHE_NAME = "models--intfloat--multilingual-e5-small"
LOCK_FILE_NAME = ".embedding-model-artifacts.lock"
CHUNK_SIZE = 1024 * 1024
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
BLOB_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ArtifactCacheError(ValueError):
    """Represent one sanitized artifact-cache integrity failure."""


@dataclass(frozen=True, slots=True)
class FileSignature:
    """Capture descriptor-relative entry identity and content timestamps."""

    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileSignature:
        """Build a signature from one stat or fstat result.

        Args:
            value: Operating-system metadata for the captured entry.

        Returns:
            The immutable seven-field entry signature.
        """
        return cls(
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    def same_directory_identity(self, other: FileSignature) -> bool:
        """Compare device, inode, and mode while ignoring directory contents.

        Args:
            other: Signature captured from the entry being compared.

        Returns:
            Whether both signatures identify the same directory entry.
        """
        return (self.device, self.inode, self.mode) == (
            other.device,
            other.inode,
            other.mode,
        )

    def same_file_content_identity(self, other: FileSignature) -> bool:
        """Compare file identity, size, and mtime, ignoring link count and ctime.

        Args:
            other: Signature captured from the file being compared.

        Returns:
            Whether both signatures identify the same file contents.
        """
        return (
            self.device,
            self.inode,
            self.mode,
            self.size,
            self.mtime_ns,
        ) == (
            other.device,
            other.inode,
            other.mode,
            other.size,
            other.mtime_ns,
        )


@dataclass(frozen=True, slots=True)
class DirectoryEvidence:
    """Capture the lexical path and identity of opened cache directories."""

    components: tuple[str, ...]
    signatures: tuple[FileSignature, ...]


@dataclass(frozen=True, slots=True)
class CachedReference:
    """Capture the exact refs/main entry read from the held model directory."""

    revision: str
    content: bytes
    directory: DirectoryEvidence
    signature: FileSignature


@dataclass(frozen=True, slots=True)
class CachedAsset:
    """Capture one fixed snapshot entry and its optional blob target."""

    name: str
    parent: DirectoryEvidence
    signature: FileSignature
    link_target: str | None
    blob_name: str | None
    blob_directory: DirectoryEvidence | None
    blob_signature: FileSignature | None


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    """Hold expected length and immutable identity for one known model asset."""

    name: str
    size: int
    lfs_sha256: str | None
    git_blob_sha1: str | None


@dataclass(frozen=True, slots=True)
class StagedAsset:
    """Identify one validated staged file and immutable Hugging Face blob name."""

    metadata: AssetMetadata
    stage_name: str
    blob_name: str


@dataclass(frozen=True, slots=True)
class AssetDigest:
    """Hold the bounded stream identity of one model asset."""

    size: int
    sha256: str | None
    git_blob_sha1: str | None


class SinkProtocol(Protocol):
    """Receive named assets as bounded chunks and verified completion calls."""

    def begin_asset(self, name: str, size: int) -> None:
        """Begin the fixed named asset with its captured byte length."""

    def write_chunk(self, chunk: bytes) -> None:
        """Transfer one bounded asset chunk to the caller-owned receiver."""

    def asset_verified(self, name: str) -> None:
        """Report that the named asset passed all stream and digest checks."""


def cache_error(reason: str) -> NoReturn:
    """Raise a stable cache error without exposing filesystem paths.

    Args:
        reason: Sanitized reason code describing the cache-integrity failure.
    """
    raise ArtifactCacheError(f"EMBEDDING_MODEL_ARTIFACT_ERROR: {reason}") from None


def relative_blob_target(parent_components: tuple[str, ...], target: str) -> str:
    """Resolve an HF snapshot target lexically to one confined blob name.

    Args:
        parent_components: Components of the snapshot entry's parent directory.
        target: Relative symlink target captured without following it.

    Returns:
        The validated direct child name below the model blobs directory.
    """
    if target.startswith("/") or "\x00" in target:
        cache_error("cached asset escapes configured model cache")
    resolved = list(parent_components)
    for component in target.split("/"):
        if component in {"", "."}:
            continue
        if component == "..":
            if not resolved:
                cache_error("cached asset escapes configured model cache")
            resolved.pop()
        else:
            resolved.append(component)
    if len(resolved) != 2 or resolved[0] != "blobs":
        cache_error("cached asset escapes configured model cache")
    blob_name = resolved[1]
    if not BLOB_PATTERN.fullmatch(blob_name):
        cache_error("cached asset blob name is invalid")
    return blob_name


def validate_cached_blob_name(blob_name: str, digest: AssetDigest) -> None:
    """Validate the checksum encoded in an existing HF blob entry name.

    Args:
        blob_name: Validated 40-character or 64-character blob basename.
        digest: Streaming digest computed from the opened blob file.
    """
    actual = digest.sha256 if len(blob_name) == 64 else digest.git_blob_sha1
    if actual != blob_name:
        cache_error("cached asset identity mismatch")


def asset_parent_components(name: str) -> tuple[str, ...]:
    """Return the lexical subdirectory components for a fixed asset name.

    Args:
        name: One name from the fixed model asset set.

    Returns:
        The parent directory components below a snapshot revision.
    """
    if name == "onnx/model.onnx":
        return ("onnx",)
    return ()


def asset_leaf_name(name: str) -> str:
    """Validate one fixed asset name and return its leaf component.

    Args:
        name: Candidate model asset name.

    Returns:
        The validated final path component.
    """
    if name not in ASSET_NAMES:
        cache_error("model asset name is invalid")
    return name.rsplit("/", maxsplit=1)[-1]
