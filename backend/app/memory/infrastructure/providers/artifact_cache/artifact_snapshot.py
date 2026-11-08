"""Inspect and stream one validated descriptor-rooted artifact snapshot."""

from __future__ import annotations

import os
import stat

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    ASSET_NAMES,
    COMMIT_PATTERN,
    AssetDigest,
    AssetMetadata,
    CachedAsset,
    CachedReference,
    DirectoryEvidence,
    FileSignature,
    SinkProtocol,
    asset_leaf_name,
    asset_parent_components,
    cache_error,
    relative_blob_target,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_reference import (
    ArtifactReferenceStore,
)
from app.memory.infrastructure.providers.artifact_cache.directory_access import (
    stat_child,
)
from app.memory.infrastructure.providers.artifact_cache.regular_files import (
    asset_hash_requirements,
    stream_regular_leaf,
    validate_asset_digest,
)
from app.memory.infrastructure.providers.artifact_cache.trusted_directory import (
    TrustedModelDirectory,
)


class ArtifactSnapshotReader:
    """Capture, recheck, and stream cache snapshot entries and content blobs."""

    def __init__(
        self,
        directory: TrustedModelDirectory,
        references: ArtifactReferenceStore,
    ) -> None:
        """Bind snapshot operations to their directory and reference owners.

        Args:
            directory: Session-owned trusted directory descriptor owner.
            references: Session-owned reference store for the fixed main ref.
        """
        self._directory = directory
        self._references = references

    def inspect_snapshot_assets(
        self,
        revision: str,
    ) -> dict[str, CachedAsset | None]:
        """Capture confined no-follow evidence for all fixed snapshot files.

        Args:
            revision: Validated model revision to inspect.

        Returns:
            A fixed-name mapping to captured asset evidence or cache misses.
        """
        if not COMMIT_PATTERN.fullmatch(revision):
            cache_error("cached revision is invalid")
        if self._directory.model_directory(create=False) is None:
            return dict.fromkeys(ASSET_NAMES)
        snapshot_directory = self._directory.open_directory_chain(
            ("snapshots", revision),
            create=False,
        )
        if snapshot_directory is None:
            return dict.fromkeys(ASSET_NAMES)
        snapshot_fd, snapshot_evidence = snapshot_directory
        os.close(snapshot_fd)

        locations: dict[str, CachedAsset | None] = {}
        for name in ASSET_NAMES:
            parent_components = (
                "snapshots",
                revision,
                *asset_parent_components(name),
            )
            parent = self._directory.open_directory_chain(
                parent_components,
                create=False,
            )
            if parent is None:
                locations[name] = None
                continue
            parent_fd, parent_evidence = parent
            try:
                locations[name] = self._capture_asset(
                    name,
                    parent_fd,
                    parent_evidence,
                )
            finally:
                os.close(parent_fd)
        self._directory.assert_directory_evidence(snapshot_evidence)
        self._directory.assert_model_entry()
        return locations

    def assert_assets_unchanged(
        self,
        locations: dict[str, CachedAsset | None],
    ) -> None:
        """Recheck captured directories, symlinks, and leaf evidence.

        Args:
            locations: Asset evidence captured before an acquisition mutation.
        """
        for name, asset in locations.items():
            if asset is None:
                continue
            parent = self._directory.open_directory_chain(
                asset.parent.components,
                create=False,
                expected=asset.parent,
            )
            if parent is None:
                cache_error("cached asset parent changed during repair")
            parent_fd, _ = parent
            try:
                leaf_name = asset_leaf_name(name)
                entry = stat_child(parent_fd, leaf_name)
                if entry is None or FileSignature.from_stat(entry) != asset.signature:
                    cache_error("cached asset changed during repair")
                if asset.link_target is not None:
                    if os.readlink(leaf_name, dir_fd=parent_fd) != asset.link_target:
                        cache_error("cached asset changed during repair")
                    if asset.blob_directory is None or asset.blob_name is None:
                        cache_error("cached asset blob evidence is invalid")
                    blob_directory = self._directory.open_directory_chain(
                        asset.blob_directory.components,
                        create=False,
                        expected=asset.blob_directory,
                    )
                    if blob_directory is None:
                        cache_error("cached asset blob directory changed")
                    blob_fd, _ = blob_directory
                    try:
                        blob_entry = stat_child(blob_fd, asset.blob_name)
                        if (
                            blob_entry is None
                            or FileSignature.from_stat(blob_entry)
                            != asset.blob_signature
                        ):
                            cache_error("cached asset blob changed during repair")
                    finally:
                        os.close(blob_fd)
            finally:
                os.close(parent_fd)
        self._directory.assert_model_entry()

    def inspect_one_asset(self, name: str, revision: str) -> CachedAsset | None:
        """Inspect one path after a competing writer may have published it.

        Args:
            name: One fixed model asset name.
            revision: Validated model revision to inspect.

        Returns:
            Captured entry evidence, or None when its parent or leaf is absent.
        """
        parent_components = (
            "snapshots",
            revision,
            *asset_parent_components(name),
        )
        parent = self._directory.open_directory_chain(
            parent_components,
            create=False,
        )
        if parent is None:
            return None
        parent_fd, parent_evidence = parent
        try:
            return self._capture_asset(name, parent_fd, parent_evidence)
        finally:
            os.close(parent_fd)

    def _capture_asset(
        self,
        name: str,
        parent_fd: int,
        parent_evidence: DirectoryEvidence,
    ) -> CachedAsset | None:
        """Capture one direct file or validated snapshot-to-blob symlink.

        Args:
            name: One fixed model asset name.
            parent_fd: Open descriptor for the asset parent directory.
            parent_evidence: Path and identity evidence for that parent.

        Returns:
            Captured asset identity, or None when its leaf is absent.
        """
        leaf_name = asset_leaf_name(name)
        entry = stat_child(parent_fd, leaf_name)
        if entry is None:
            return None
        entry_signature = FileSignature.from_stat(entry)
        if stat.S_ISREG(entry.st_mode):
            return CachedAsset(
                name,
                parent_evidence,
                entry_signature,
                None,
                None,
                None,
                None,
            )
        if not stat.S_ISLNK(entry.st_mode):
            cache_error("cached asset path is invalid")
        target = os.readlink(leaf_name, dir_fd=parent_fd)
        blob_name = relative_blob_target(parent_evidence.components, target)
        blob_directory = self._directory.open_directory_chain(
            ("blobs",),
            create=False,
        )
        if blob_directory is None:
            cache_error("cached asset blob is missing")
        blob_fd, blob_evidence = blob_directory
        try:
            blob_entry = stat_child(blob_fd, blob_name)
            if blob_entry is None or not stat.S_ISREG(blob_entry.st_mode):
                cache_error("cached asset blob is invalid")
            current = stat_child(parent_fd, leaf_name)
            if (
                current is None
                or FileSignature.from_stat(current) != entry_signature
                or os.readlink(leaf_name, dir_fd=parent_fd) != target
            ):
                cache_error("cached snapshot changed during inspection")
            return CachedAsset(
                name,
                parent_evidence,
                entry_signature,
                target,
                blob_name,
                blob_evidence,
                FileSignature.from_stat(blob_entry),
            )
        finally:
            os.close(blob_fd)

    def stream_cached_asset(
        self,
        asset: CachedAsset,
        sink: SinkProtocol | None = None,
        metadata: AssetMetadata | None = None,
    ) -> AssetDigest:
        """Stream and validate one captured asset through anchored no-follow fds.

        Args:
            asset: Asset entry and identities captured during inspection.
            sink: Optional caller-owned receiver for the validated file chunks.
            metadata: Optional expected length and remote content identities.

        Returns:
            The validated asset length and requested content digests.
        """
        parent = self._directory.open_directory_chain(
            asset.parent.components,
            create=False,
            expected=asset.parent,
        )
        if parent is None:
            cache_error("cached asset parent changed during read")
        parent_fd, parent_evidence = parent
        blob_fd: int | None = None
        try:
            leaf_name = asset_leaf_name(asset.name)
            entry = stat_child(parent_fd, leaf_name)
            if entry is None or FileSignature.from_stat(entry) != asset.signature:
                cache_error("cached asset changed during read")
            need_sha256, need_git_sha1 = asset_hash_requirements(asset, metadata)
            if asset.link_target is not None:
                if not stat.S_ISLNK(entry.st_mode):
                    cache_error("cached asset changed during read")
                if os.readlink(leaf_name, dir_fd=parent_fd) != asset.link_target:
                    cache_error("cached asset changed during read")
                if (
                    asset.blob_name is None
                    or asset.blob_directory is None
                    or asset.blob_signature is None
                ):
                    cache_error("cached asset blob evidence is invalid")
                blob_directory = self._directory.open_directory_chain(
                    asset.blob_directory.components,
                    create=False,
                    expected=asset.blob_directory,
                )
                if blob_directory is None:
                    cache_error("cached asset blob directory changed")
                blob_fd, _ = blob_directory
                digest = stream_regular_leaf(
                    blob_fd,
                    asset.blob_name,
                    expected=asset.blob_signature,
                    asset_name=asset.name,
                    sink=sink,
                    need_sha256=need_sha256,
                    need_git_sha1=need_git_sha1,
                    expected_size=metadata.size if metadata is not None else None,
                )
                blob_entry = stat_child(blob_fd, asset.blob_name)
                if (
                    blob_entry is None
                    or FileSignature.from_stat(blob_entry) != asset.blob_signature
                ):
                    cache_error("cached asset blob changed during read")
                self._directory.assert_directory_evidence(asset.blob_directory)
            else:
                if not stat.S_ISREG(entry.st_mode):
                    cache_error("cached asset path is invalid")
                digest = stream_regular_leaf(
                    parent_fd,
                    leaf_name,
                    expected=asset.signature,
                    asset_name=asset.name,
                    sink=sink,
                    need_sha256=need_sha256,
                    need_git_sha1=need_git_sha1,
                    expected_size=metadata.size if metadata is not None else None,
                )
            current_entry = stat_child(parent_fd, leaf_name)
            if (
                current_entry is None
                or FileSignature.from_stat(current_entry) != asset.signature
            ):
                cache_error("cached snapshot changed during read")
            if asset.link_target is not None and (
                os.readlink(leaf_name, dir_fd=parent_fd) != asset.link_target
            ):
                cache_error("cached snapshot changed during read")
            self._directory.assert_directory_evidence(parent_evidence)
            self._directory.assert_model_entry()
            validate_asset_digest(asset, digest, metadata)
            return digest
        finally:
            if blob_fd is not None:
                os.close(blob_fd)
            os.close(parent_fd)

    def stream_complete_snapshot(
        self,
        sink: SinkProtocol,
        *,
        expected_revision: str | None = None,
    ) -> str | None:
        """Stream a complete offline snapshot without creating cache files.

        Args:
            sink: Caller-owned receiver for bounded asset chunks.
            expected_revision: Optional revision fence from an active acquisition.

        Returns:
            The validated pinned revision, or None when the cache is incomplete.
        """
        if self._directory.model_directory(create=False) is None:
            return None
        reference = self._references.read_reference()
        if reference is None:
            return None
        if expected_revision is not None and reference.revision != expected_revision:
            cache_error("cached reference changed during acquisition")
        locations = self.inspect_snapshot_assets(reference.revision)
        if any(location is None for location in locations.values()):
            return None
        for name in ASSET_NAMES:
            location = locations[name]
            if location is None:
                cache_error("cached snapshot is incomplete")
            self.stream_cached_asset(location, sink)
            sink.asset_verified(name)
        self.assert_assets_unchanged(locations)
        current_reference: CachedReference | None = self._references.read_reference()
        if current_reference != reference:
            cache_error("cached reference changed during read")
        self._directory.assert_model_entry()
        return reference.revision
