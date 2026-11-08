"""Publish validated immutable blobs and revision-scoped snapshot links."""

from __future__ import annotations

import os
import posixpath
import stat
from contextlib import suppress

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    ASSET_NAMES,
    COMMIT_PATTERN,
    AssetMetadata,
    CachedAsset,
    DirectoryEvidence,
    FileSignature,
    StagedAsset,
    asset_leaf_name,
    asset_parent_components,
    cache_error,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_snapshot import (
    ArtifactSnapshotReader,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_staging import (
    ArtifactStaging,
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


class ArtifactPublisher:
    """Publish one validated snapshot through trusted directory descriptors."""

    def __init__(
        self,
        directory: TrustedModelDirectory,
        reader: ArtifactSnapshotReader,
    ) -> None:
        """Bind publication to the shared session directory and snapshot reader.

        Args:
            directory: Session-owned trusted directory descriptor owner.
            reader: Session-owned snapshot reader for existing asset evidence.
        """
        self._directory = directory
        self._reader = reader

    def publish_assets(
        self,
        *,
        revision: str,
        locations: dict[str, CachedAsset | None],
        staged_assets: dict[str, StagedAsset],
        staging: ArtifactStaging,
    ) -> None:
        """Publish immutable blobs and links after all downloads validate.

        Args:
            revision: Validated model commit revision for the snapshot directory.
            locations: Asset evidence captured before download and staging.
            staged_assets: Validated staged files that still need publication.
            staging: Owner of staged files and their directory descriptor.
        """
        if not staged_assets:
            return
        if not COMMIT_PATTERN.fullmatch(revision):
            cache_error("published revision is invalid")
        model_fd = self._directory.require_model_directory()
        blob_directory = self._directory.open_directory_chain(
            ("blobs",),
            create=True,
        )
        if blob_directory is None:
            cache_error("model blob directory could not be created")
        blob_fd, blob_evidence = blob_directory
        try:
            for name in ASSET_NAMES:
                staged = staged_assets.get(name)
                if staged is None:
                    continue
                self._validate_existing_blob(blob_fd, staged)
            for staged in staged_assets.values():
                with suppress(FileExistsError):
                    staging.link_to_blob(
                        staged.stage_name,
                        blob_fd,
                        staged.blob_name,
                    )
                self._validate_existing_blob(blob_fd, staged)
            os.fsync(blob_fd)
            self._directory.assert_directory_evidence(blob_evidence)
            os.fsync(model_fd)
        finally:
            os.close(blob_fd)

        snapshots = self._directory.open_directory_chain(
            ("snapshots",),
            create=True,
        )
        if snapshots is None:
            cache_error("snapshot directory could not be created")
        snapshots_fd, snapshots_evidence = snapshots
        try:
            snapshot = self._directory.open_directory_chain(
                ("snapshots", revision),
                create=True,
            )
            if snapshot is None:
                cache_error("snapshot revision directory could not be created")
            snapshot_fd, snapshot_evidence = snapshot
            try:
                for name in ASSET_NAMES:
                    if locations[name] is not None:
                        continue
                    staged = staged_assets.get(name)
                    if staged is None:
                        cache_error("staged model asset is missing")
                    parent_components = (
                        "snapshots",
                        revision,
                        *asset_parent_components(name),
                    )
                    parent = self._directory.open_directory_chain(
                        parent_components,
                        create=True,
                    )
                    if parent is None:
                        cache_error("snapshot asset directory could not be created")
                    parent_fd, parent_evidence = parent
                    try:
                        leaf_name = asset_leaf_name(name)
                        existing = stat_child(parent_fd, leaf_name)
                        if existing is not None:
                            current = self._reader.inspect_one_asset(name, revision)
                            if current is None:
                                cache_error("conflicting cached asset")
                            self._reader.stream_cached_asset(
                                current,
                                metadata=staged.metadata,
                            )
                            continue
                        target = posixpath.relpath(
                            f"blobs/{staged.blob_name}",
                            start=posixpath.join(*parent_components),
                        )
                        os.symlink(target, leaf_name, dir_fd=parent_fd)
                        linked = stat_child(parent_fd, leaf_name)
                        if linked is None or not stat.S_ISLNK(linked.st_mode):
                            cache_error("published snapshot entry is invalid")
                        if os.readlink(leaf_name, dir_fd=parent_fd) != target:
                            cache_error("published snapshot entry changed")
                        os.fsync(parent_fd)
                        self._directory.assert_directory_evidence(parent_evidence)
                    finally:
                        os.close(parent_fd)
                os.fsync(snapshot_fd)
                self._directory.assert_directory_evidence(snapshot_evidence)
            finally:
                os.close(snapshot_fd)
            os.fsync(snapshots_fd)
            self._directory.assert_directory_evidence(snapshots_evidence)
            os.fsync(model_fd)
        finally:
            os.close(snapshots_fd)
        self._directory.assert_model_entry()

    def _validate_existing_blob(self, blob_fd: int, staged: StagedAsset) -> None:
        """Fail before publication if an immutable blob name already conflicts.

        Args:
            blob_fd: Borrowed descriptor for the model blob directory.
            staged: Validated staged file and expected remote content identity.
        """
        entry = stat_child(blob_fd, staged.blob_name)
        if entry is None:
            return
        if not stat.S_ISREG(entry.st_mode):
            cache_error("conflicting cached blob")
        expected: AssetMetadata = staged.metadata
        asset = CachedAsset(
            expected.name,
            DirectoryEvidence(
                ("blobs",),
                (FileSignature.from_stat(os.fstat(blob_fd)),),
            ),
            FileSignature.from_stat(entry),
            None,
            staged.blob_name,
            None,
            None,
        )
        need_sha256, need_git_sha1 = asset_hash_requirements(asset, expected)
        digest = stream_regular_leaf(
            blob_fd,
            staged.blob_name,
            expected=FileSignature.from_stat(entry),
            asset_name=staged.metadata.name,
            sink=None,
            need_sha256=need_sha256,
            need_git_sha1=need_git_sha1,
            expected_size=expected.size,
        )
        validate_asset_digest(asset, digest, expected)
