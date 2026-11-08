"""Own and validate the persistent cache root and model directory descriptors."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    LOCK_FILE_NAME,
    MODEL_CACHE_NAME,
    DirectoryEvidence,
    FileSignature,
    cache_error,
)
from app.memory.infrastructure.providers.artifact_cache.directory_access import (
    open_child_directory,
    open_root_directory,
    stat_child,
)


class TrustedModelDirectory:
    """Hold one trusted root/model descriptor pair for a cache session."""

    def __init__(self, root_path: Path) -> None:
        """Open the existing root without creating cache state.

        Args:
            root_path: Absolute configured cache root path.
        """
        self.root_path = root_path
        self._root_fd = open_root_directory(root_path, create=False)
        self._model_fd: int | None = None
        self._model_signature: FileSignature | None = None

    def __enter__(self) -> TrustedModelDirectory:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        model_fd, self._model_fd = self._model_fd, None
        root_fd, self._root_fd = self._root_fd, None
        self._model_signature = None
        cleanup_failed = False
        for descriptor in (model_fd, root_fd):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except BaseException:
                cleanup_failed = True
        if cleanup_failed:
            if isinstance(exc_value, BaseException):
                exc_value.add_note("artifact cache descriptor cleanup also failed")
                return
            cache_error("cache descriptor cleanup failed")

    def ensure_model_directory(self) -> None:
        """Create the configured root chain and fixed model directory securely.

        Raises:
            ArtifactCacheError: The root or model directory could not be secured.
        """
        if self._root_fd is None:
            self._root_fd = open_root_directory(self.root_path, create=True)
        if self._root_fd is None:
            cache_error("configured cache root could not be created")
        if self._model_fd is None:
            opened = open_child_directory(
                self._root_fd,
                MODEL_CACHE_NAME,
                create=True,
            )
            if opened is None:
                cache_error("model cache directory could not be created")
            self._model_fd, self._model_signature = opened
        self.assert_model_entry()

    def model_directory(self, *, create: bool) -> int | None:
        """Return the borrowed model descriptor, opening it when needed.

        Args:
            create: Create the configured root and model directory if absent.

        Returns:
            A borrowed model directory descriptor, or None when absent.
        """
        if self._model_fd is not None:
            self.assert_model_entry()
            return self._model_fd
        if self._root_fd is None:
            if not create:
                return None
            self._root_fd = open_root_directory(self.root_path, create=True)
        if self._root_fd is None:
            return None
        opened = open_child_directory(
            self._root_fd,
            MODEL_CACHE_NAME,
            create=create,
        )
        if opened is None:
            return None
        self._model_fd, self._model_signature = opened
        return self._model_fd

    def require_model_directory(self) -> int:
        """Create or return the model directory as a borrowed descriptor.

        Returns:
            A borrowed descriptor owned until this directory context exits.
        """
        model_fd = self.model_directory(create=True)
        if model_fd is None:
            cache_error("model cache directory is unavailable")
        return model_fd

    def assert_model_entry(self) -> None:
        """Verify that the held root entry and descriptor still identify one directory."""
        root_fd = self._root_fd
        model_fd = self._model_fd
        model_signature = self._model_signature
        if root_fd is None or model_fd is None or model_signature is None:
            cache_error("model cache descriptor is unavailable")
        entry = stat_child(root_fd, MODEL_CACHE_NAME)
        if (
            entry is None
            or not stat.S_ISDIR(entry.st_mode)
            or not FileSignature.from_stat(entry).same_directory_identity(
                model_signature
            )
            or not FileSignature.from_stat(os.fstat(model_fd)).same_directory_identity(
                model_signature
            )
        ):
            cache_error("model cache directory changed during access")

    def open_directory_chain(
        self,
        components: tuple[str, ...],
        *,
        create: bool,
        expected: DirectoryEvidence | None = None,
    ) -> tuple[int, DirectoryEvidence] | None:
        """Open a chain below the model directory and capture each identity.

        Args:
            components: Lexical directory components below the model directory.
            create: Create missing components with private permissions.
            expected: Optional evidence that every opened component must match.

        Returns:
            An owned final descriptor and its evidence, or None when absent.
        """
        model_fd = self.model_directory(create=create)
        if model_fd is None:
            return None
        current_fd = os.dup(model_fd)
        signatures: list[FileSignature] = []
        if expected is not None and (
            expected.components != components
            or len(expected.signatures) != len(components)
        ):
            os.close(current_fd)
            cache_error("cache directory evidence is invalid")
        try:
            for index, component in enumerate(components):
                opened = open_child_directory(
                    current_fd,
                    component,
                    create=create,
                )
                if opened is None:
                    os.close(current_fd)
                    return None
                next_fd, signature = opened
                if expected is not None and not signature.same_directory_identity(
                    expected.signatures[index]
                ):
                    os.close(next_fd)
                    cache_error("cache directory changed during access")
                signatures.append(signature)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd, DirectoryEvidence(components, tuple(signatures))
        except BaseException:
            os.close(current_fd)
            raise

    def assert_directory_evidence(self, evidence: DirectoryEvidence) -> None:
        """Reopen captured path evidence and reject directory replacement.

        Args:
            evidence: Directory path and signatures captured earlier.
        """
        opened = self.open_directory_chain(
            evidence.components,
            create=False,
            expected=evidence,
        )
        if opened is None:
            cache_error("cache directory changed during access")
        descriptor, _ = opened
        os.close(descriptor)


class CacheMutationLock:
    """Serialize cooperating writers through the model-local flock file."""

    def __init__(self, directory: TrustedModelDirectory) -> None:
        """Bind lock operations to the one trusted model directory owner.

        Args:
            directory: Session-owned trusted directory descriptor owner.
        """
        self._directory = directory

    @contextmanager
    def exclusive_lock(self) -> Generator[None]:
        """Hold the existing exclusive lock file under the model descriptor.

        Yields:
            None while this process holds the model artifact mutation lock.
        """
        model_fd = self._directory.require_model_directory()
        descriptor = self._open_lock_file(model_fd)
        locked = False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            self._assert_lock_file(descriptor)
            self._directory.assert_model_entry()
            yield
        finally:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _open_lock_file(self, model_fd: int) -> int:
        """Open or create the regular lock file relative to the model descriptor.

        Args:
            model_fd: Borrowed descriptor for the held model directory.

        Returns:
            An owned lock-file descriptor.
        """
        name = LOCK_FILE_NAME
        entry = stat_child(model_fd, name)
        created = entry is None
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        if created:
            try:
                descriptor = os.open(
                    name,
                    flags | os.O_CREAT | os.O_EXCL,
                    mode=0o600,
                    dir_fd=model_fd,
                )
            except FileExistsError:
                created = False
                entry = stat_child(model_fd, name)
                if entry is None:
                    cache_error("cache lock path changed during creation")
                descriptor = os.open(name, flags, dir_fd=model_fd)
        else:
            descriptor = os.open(name, flags, dir_fd=model_fd)
        try:
            opened = FileSignature.from_stat(os.fstat(descriptor))
            after = stat_child(model_fd, name)
            if (
                not stat.S_ISREG(opened.mode)
                or after is None
                or not opened.same_file_content_identity(FileSignature.from_stat(after))
                or (
                    entry is not None
                    and not FileSignature.from_stat(entry).same_file_content_identity(
                        opened
                    )
                )
            ):
                cache_error("cache lock path is invalid")
            if created:
                os.fsync(model_fd)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _assert_lock_file(self, descriptor: int) -> None:
        """Ensure the lock name still refers to the descriptor being held.

        Args:
            descriptor: Open lock-file descriptor protected by flock.
        """
        model_fd = self._directory.require_model_directory()
        entry = stat_child(model_fd, LOCK_FILE_NAME)
        opened = FileSignature.from_stat(os.fstat(descriptor))
        if (
            entry is None
            or not stat.S_ISREG(entry.st_mode)
            or not FileSignature.from_stat(entry).same_file_content_identity(opened)
        ):
            cache_error("cache lock path changed during acquisition")
