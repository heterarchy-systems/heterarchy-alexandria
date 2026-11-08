"""Read, fence, and publish the fixed artifact-cache revision reference."""

from __future__ import annotations

import os
import stat
import uuid

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    COMMIT_PATTERN,
    CachedReference,
    FileSignature,
    cache_error,
)
from app.memory.infrastructure.providers.artifact_cache.directory_access import (
    stat_child,
)
from app.memory.infrastructure.providers.artifact_cache.regular_files import (
    read_regular_leaf,
)
from app.memory.infrastructure.providers.artifact_cache.trusted_directory import (
    TrustedModelDirectory,
)

_CREATE_LEAF_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK
)


class ArtifactReferenceStore:
    """Own revision-reference semantics for one trusted directory session."""

    def __init__(self, directory: TrustedModelDirectory) -> None:
        """Bind reference reads and publication to the session directory owner.

        Args:
            directory: Session-owned trusted directory descriptor owner.
        """
        self._directory = directory

    def read_reference(self) -> CachedReference | None:
        """Read the fixed commit ref through a no-follow descriptor-relative open.

        Returns:
            The captured revision reference, or None when it is absent.
        """
        model_fd = self._directory.model_directory(create=False)
        if model_fd is None:
            return None
        opened = self._directory.open_directory_chain(("refs",), create=False)
        if opened is None:
            return None
        refs_fd, refs_evidence = opened
        try:
            entry = stat_child(refs_fd, "main")
            if entry is None:
                return None
            if not stat.S_ISREG(entry.st_mode) or entry.st_size > 128:
                cache_error("cached reference path is invalid")
            content, signature = read_regular_leaf(
                refs_fd,
                "main",
                expected=FileSignature.from_stat(entry),
            )
            if len(content) > 128:
                cache_error("cached reference is malformed")
            try:
                text = content.decode("ascii")
            except UnicodeDecodeError:
                cache_error("cached reference is malformed")
            revision = text.strip()
            if (
                not revision
                or not COMMIT_PATTERN.fullmatch(revision)
                or len(text.splitlines()) != 1
            ):
                cache_error("cached reference is malformed")
            self._directory.assert_directory_evidence(refs_evidence)
            self._directory.assert_model_entry()
            return CachedReference(revision, content, refs_evidence, signature)
        finally:
            os.close(refs_fd)

    def assert_reference_unchanged(
        self,
        original: CachedReference | None,
        expected_revision: str,
    ) -> None:
        """Reject ref drift before publishing files for another revision.

        Args:
            original: Exact reference captured before acquisition.
            expected_revision: Revision the staged snapshot will publish.
        """
        current = self.read_reference()
        if original is None:
            if current is not None and current.revision != expected_revision:
                cache_error("conflicting cached reference")
            return
        if current != original:
            cache_error("cached reference changed during repair")

    def publish_reference(self, revision: str) -> None:
        """Atomically create an absent main ref after its snapshot is complete.

        Args:
            revision: Validated immutable model commit revision.
        """
        if not COMMIT_PATTERN.fullmatch(revision):
            cache_error("published reference is invalid")
        model_fd = self._directory.require_model_directory()
        refs = self._directory.open_directory_chain(("refs",), create=True)
        if refs is None:
            cache_error("reference directory could not be created")
        refs_fd, refs_evidence = refs
        try:
            existing = self.read_reference()
            if existing is not None:
                if existing.revision != revision:
                    cache_error("conflicting cached reference")
                return
            temp_name = f".main-{uuid.uuid4().hex}.tmp"
            descriptor = os.open(
                temp_name,
                _CREATE_LEAF_FLAGS,
                mode=0o600,
                dir_fd=refs_fd,
            )
            temp_identity: FileSignature | None = None
            descriptor_owned = True
            operation_failed = False
            try:
                try:
                    opened_before = os.fstat(descriptor)
                    if not stat.S_ISREG(opened_before.st_mode):
                        cache_error("temporary reference is not a regular file")
                    temp_identity = FileSignature.from_stat(opened_before)
                    stream = os.fdopen(descriptor, "wb")
                    descriptor_owned = False
                    with stream:
                        stream.write(f"{revision}\n".encode("ascii"))
                        stream.flush()
                        os.fsync(stream.fileno())
                        temp_signature = FileSignature.from_stat(
                            os.fstat(stream.fileno())
                        )
                    temp_entry = stat_child(refs_fd, temp_name)
                    if (
                        temp_entry is None
                        or FileSignature.from_stat(temp_entry) != temp_signature
                    ):
                        cache_error("temporary reference changed before publication")
                    try:
                        os.link(
                            temp_name,
                            "main",
                            src_dir_fd=refs_fd,
                            dst_dir_fd=refs_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        current = self.read_reference()
                        if current is None or current.revision != revision:
                            cache_error("conflicting cached reference")
                    else:
                        published = stat_child(refs_fd, "main")
                        if (
                            published is None
                            or not stat.S_ISREG(published.st_mode)
                            or published.st_dev != temp_entry.st_dev
                            or published.st_ino != temp_entry.st_ino
                        ):
                            cache_error("published reference changed during link")
                except BaseException as error:
                    operation_failed = True
                    if descriptor_owned:
                        descriptor_owned = False
                        try:
                            os.close(descriptor)
                        except BaseException:
                            error.add_note(
                                "artifact reference descriptor cleanup also failed"
                            )
                    raise
            finally:
                if temp_identity is not None:
                    try:
                        current_temp = stat_child(refs_fd, temp_name)
                        if (
                            current_temp is not None
                            and temp_identity.same_directory_identity(
                                FileSignature.from_stat(current_temp)
                            )
                        ):
                            os.unlink(temp_name, dir_fd=refs_fd)
                    except BaseException:
                        if not operation_failed:
                            raise
            os.fsync(refs_fd)
            self._directory.assert_directory_evidence(refs_evidence)
            os.fsync(model_fd)
        finally:
            os.close(refs_fd)
        self._directory.assert_model_entry()
