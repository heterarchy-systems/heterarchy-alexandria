"""Compose one scoped descriptor owner with its artifact-cache collaborators."""

from __future__ import annotations

from pathlib import Path

from app.memory.infrastructure.providers.artifact_cache.artifact_publication import (
    ArtifactPublisher,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_reference import (
    ArtifactReferenceStore,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_snapshot import (
    ArtifactSnapshotReader,
)
from app.memory.infrastructure.providers.artifact_cache.trusted_directory import (
    CacheMutationLock,
    TrustedModelDirectory,
)


class ArtifactCache:
    """Hold one root descriptor owner and its cache-specific collaborators."""

    def __init__(self, root: Path) -> None:
        """Compose all cache operations around one trusted directory owner.

        Args:
            root: Absolute configured cache root path.

        Raises:
            ArtifactCacheError: The cache root path is invalid or cannot be opened.
        """
        directory = TrustedModelDirectory(root)
        try:
            self._directory = directory
            self._references = ArtifactReferenceStore(directory)
            self._reader = ArtifactSnapshotReader(directory, self._references)
            self._publisher = ArtifactPublisher(directory, self._reader)
            self._mutation_lock = CacheMutationLock(directory)
        except BaseException as error:
            directory.__exit__(type(error), error, error.__traceback__)
            raise

    @property
    def directory(self) -> TrustedModelDirectory:
        """Return this session's single trusted directory owner."""
        return self._directory

    @property
    def mutation_lock(self) -> CacheMutationLock:
        """Return the model-local mutation lock bound to the directory owner."""
        return self._mutation_lock

    @property
    def references(self) -> ArtifactReferenceStore:
        """Return the reference store bound to the directory owner."""
        return self._references

    @property
    def reader(self) -> ArtifactSnapshotReader:
        """Return the snapshot reader bound to the directory and ref stores."""
        return self._reader

    @property
    def publisher(self) -> ArtifactPublisher:
        """Return the publisher bound to the directory and snapshot reader."""
        return self._publisher

    def __enter__(self) -> ArtifactCache:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._directory.__exit__(exc_type, exc_value, traceback)
