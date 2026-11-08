"""Own temporary staging files under the held model directory descriptor."""

from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Generator
from contextlib import contextmanager, suppress
from typing import BinaryIO

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    ArtifactCacheError,
    FileSignature,
    cache_error,
)
from app.memory.infrastructure.providers.artifact_cache.directory_access import (
    open_child_directory,
    stat_child,
    validate_component,
)
from app.memory.infrastructure.providers.artifact_cache.regular_files import (
    open_regular_leaf,
)
from app.memory.infrastructure.providers.artifact_cache.trusted_directory import (
    TrustedModelDirectory,
)

_CREATE_LEAF_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK
)


class ArtifactStaging:
    """Own one private staging directory and its validated staged files."""

    def __init__(
        self,
        directory: TrustedModelDirectory,
        name: str,
        descriptor: int,
        signature: FileSignature,
    ) -> None:
        """Capture ownership of a validated staging directory descriptor.

        Args:
            directory: Session-owned trusted directory descriptor owner.
            name: Random private staging directory name below the model cache.
            descriptor: Open staging directory descriptor transferred to this owner.
            signature: Directory entry evidence captured when it was opened.
        """
        self._directory = directory
        self._name = name
        self._descriptor = descriptor
        self._signature = signature
        self._files: dict[str, FileSignature] = {}

    @contextmanager
    def create_file(self, name: str) -> Generator[BinaryIO]:
        """Create one fixed-name staged file and fsync it before closing.

        Args:
            name: Single staged asset filename.

        Yields:
            A binary stream owned by the staging context.
        """
        validate_component(name)
        descriptor = os.open(
            name,
            _CREATE_LEAF_FLAGS,
            mode=0o600,
            dir_fd=self._descriptor,
        )
        descriptor_owned = True
        owned_identity: FileSignature | None = None
        try:
            opened_before = os.fstat(descriptor)
            if not stat.S_ISREG(opened_before.st_mode):
                cache_error("staged asset is not a regular file")
            owned_identity = FileSignature.from_stat(opened_before)
            stream = os.fdopen(descriptor, "wb")
            descriptor_owned = False
            with stream:
                yield stream
                stream.flush()
                os.fsync(stream.fileno())
                opened_after = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened_after.st_mode):
                    cache_error("staged asset changed during write")
                signature = FileSignature.from_stat(opened_after)
            entry = stat_child(self._descriptor, name)
            if entry is None or FileSignature.from_stat(entry) != signature:
                cache_error("staged asset changed during write")
            self._files[name] = signature
        except BaseException:
            if descriptor_owned:
                with suppress(BaseException):
                    os.close(descriptor)
            if owned_identity is not None:
                try:
                    entry = stat_child(self._descriptor, name)
                    if entry is not None and owned_identity.same_directory_identity(
                        FileSignature.from_stat(entry)
                    ):
                        os.unlink(name, dir_fd=self._descriptor)
                except BaseException:
                    pass
            raise

    def fsync(self) -> None:
        """Persist staged directory entries before publishing blob links."""
        self._assert_directory_entry()
        os.fsync(self._descriptor)

    def link_to_blob(self, stage_name: str, blob_fd: int, blob_name: str) -> None:
        """Atomically create one no-clobber hard link into the blob directory.

        Args:
            stage_name: Validated filename in this staging directory.
            blob_fd: Borrowed descriptor for the model blob directory.
            blob_name: Validated immutable content digest filename.
        """
        validate_component(stage_name)
        validate_component(blob_name)
        expected = self._files.get(stage_name)
        if expected is None:
            cache_error("staged asset is missing")
        descriptor, signature = open_regular_leaf(
            self._descriptor,
            stage_name,
            expected=expected,
        )
        os.close(descriptor)
        if signature != expected:
            cache_error("staged asset changed before publication")
        self._assert_directory_entry()
        os.link(
            stage_name,
            blob_name,
            src_dir_fd=self._descriptor,
            dst_dir_fd=blob_fd,
            follow_symlinks=False,
        )
        linked = stat_child(blob_fd, blob_name)
        if linked is None or not stat.S_ISREG(linked.st_mode):
            cache_error("published blob is not a regular file")
        staged_entry = stat_child(self._descriptor, stage_name)
        if staged_entry is None or not stat.S_ISREG(staged_entry.st_mode):
            cache_error("staged asset changed during publication")
        staged_signature = FileSignature.from_stat(staged_entry)
        if (
            linked.st_dev != staged_entry.st_dev
            or linked.st_ino != staged_entry.st_ino
            or not FileSignature.from_stat(
                os.fstat(self._descriptor)
            ).same_directory_identity(self._signature)
            or not staged_signature.same_file_content_identity(expected)
        ):
            cache_error("staged asset changed during publication")
        self._files[stage_name] = staged_signature

    def close(self) -> None:
        """Remove validated staged entries and the directory through held fds."""
        if self._descriptor < 0:
            return
        descriptor = self._descriptor
        cleanup_error: BaseException | None = None
        safe_to_remove_directory = True
        try:
            for name, expected in self._files.items():
                try:
                    entry = stat_child(descriptor, name)
                    if entry is None:
                        continue
                    if FileSignature.from_stat(entry) != expected:
                        safe_to_remove_directory = False
                        if cleanup_error is None:
                            cleanup_error = ArtifactCacheError(
                                "EMBEDDING_MODEL_ARTIFACT_ERROR: staged asset changed before cleanup"
                            )
                        continue
                    os.unlink(name, dir_fd=descriptor)
                except BaseException as error:
                    safe_to_remove_directory = False
                    if cleanup_error is None:
                        cleanup_error = error
            if safe_to_remove_directory:
                model_fd = self._directory.require_model_directory()
                current = stat_child(model_fd, self._name)
                if current is None or not FileSignature.from_stat(
                    current
                ).same_directory_identity(self._signature):
                    cleanup_error = ArtifactCacheError(
                        "EMBEDDING_MODEL_ARTIFACT_ERROR: staging directory changed before cleanup"
                    )
                else:
                    os.rmdir(self._name, dir_fd=model_fd)
                    os.fsync(model_fd)
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
        finally:
            self._descriptor = -1
            try:
                os.close(descriptor)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None:
            raise cleanup_error

    def _assert_directory_entry(self) -> None:
        """Ensure the name still denotes the held staging directory descriptor."""
        entry = stat_child(self._directory.require_model_directory(), self._name)
        if (
            entry is None
            or not stat.S_ISDIR(entry.st_mode)
            or not FileSignature.from_stat(entry).same_directory_identity(
                self._signature
            )
            or not FileSignature.from_stat(
                os.fstat(self._descriptor)
            ).same_directory_identity(self._signature)
        ):
            cache_error("staging directory changed during access")

    def __enter__(self) -> ArtifactStaging:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        try:
            self.close()
        except BaseException as cleanup_error:
            if isinstance(exc_value, BaseException):
                detail = (
                    str(cleanup_error)
                    if isinstance(cleanup_error, ArtifactCacheError)
                    else "EMBEDDING_MODEL_ARTIFACT_ERROR: cache staging cleanup failed"
                )
                exc_value.add_note(f"staging cleanup also failed: {detail}")
                return
            raise


@contextmanager
def staging_directory(
    directory: TrustedModelDirectory,
) -> Generator[ArtifactStaging]:
    """Create and own one fsynced descriptor-rooted staging directory.

    Args:
        directory: Session-owned trusted directory descriptor owner.

    Yields:
        An artifact staging owner for the private temporary directory.
    """
    model_fd = directory.require_model_directory()
    name = f".embedding-artifacts-{uuid.uuid4().hex}"
    os.mkdir(name, mode=0o700, dir_fd=model_fd)
    created_signature: FileSignature | None = None
    descriptor: int | None = None
    staging: ArtifactStaging | None = None
    try:
        created_entry = stat_child(model_fd, name)
        if created_entry is None or not stat.S_ISDIR(created_entry.st_mode):
            cache_error("staging directory changed during creation")
        created_signature = FileSignature.from_stat(created_entry)
        os.fsync(model_fd)
        opened = open_child_directory(model_fd, name)
        if opened is None:
            cache_error("staging directory could not be opened")
        descriptor, signature = opened
        if not created_signature.same_directory_identity(signature):
            cache_error("staging directory changed during creation")
        staging = ArtifactStaging(directory, name, descriptor, signature)
        descriptor = None
        with staging:
            yield staging
    except BaseException:
        if staging is None:
            if descriptor is not None:
                with suppress(BaseException):
                    os.close(descriptor)
            if created_signature is not None:
                candidate_fd: int | None = None
                try:
                    current = stat_child(model_fd, name)
                    if (
                        current is not None
                        and stat.S_ISDIR(current.st_mode)
                        and created_signature.same_directory_identity(
                            FileSignature.from_stat(current)
                        )
                    ):
                        candidate = open_child_directory(model_fd, name)
                        if candidate is not None:
                            candidate_fd, candidate_signature = candidate
                            held_signature = FileSignature.from_stat(
                                os.fstat(candidate_fd)
                            )
                            current = stat_child(model_fd, name)
                            if (
                                candidate_signature.same_directory_identity(
                                    created_signature
                                )
                                and held_signature.same_directory_identity(
                                    created_signature
                                )
                                and current is not None
                                and created_signature.same_directory_identity(
                                    FileSignature.from_stat(current)
                                )
                                and not os.listdir(candidate_fd)
                            ):
                                os.rmdir(name, dir_fd=model_fd)
                                os.fsync(model_fd)
                except BaseException:
                    pass
                finally:
                    if candidate_fd is not None:
                        with suppress(BaseException):
                            os.close(candidate_fd)
        raise
