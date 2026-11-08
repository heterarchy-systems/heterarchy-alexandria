"""Regression coverage for embedding artifact cache cleanup races."""

import errno
import os
import stat
from pathlib import Path

import pytest

from app.memory.infrastructure.providers.artifact_cache.artifact_session import (
    ArtifactCache,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_staging import (
    staging_directory,
)

MODEL_CACHE_NAME = "models--intfloat--multilingual-e5-small"
REVISION = "a" * 40
FOREIGN_CONTENT = b"foreign replacement"


def test_publish_reference_preserves_replaced_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed publish must not unlink a replacement at the temporary name."""
    cache_root = tmp_path / "cache"
    refs_directory = cache_root / MODEL_CACHE_NAME / "refs"
    temporary_path: Path | None = None
    temporary_descriptor = -1
    real_fsync = os.fsync

    def replace_temporary_file_before_fsync(descriptor: int) -> None:
        nonlocal temporary_descriptor, temporary_path
        opened = os.fstat(descriptor)
        if stat.S_ISREG(opened.st_mode) and refs_directory.is_dir():
            candidates = list(refs_directory.glob(".main-*.tmp"))
            matching = [
                path
                for path in candidates
                if (entry := path.stat()).st_dev == opened.st_dev
                and entry.st_ino == opened.st_ino
            ]
            if matching:
                assert len(matching) == 1
                temporary_path = matching[0]
                temporary_descriptor = descriptor
                temporary_path.unlink()
                temporary_path.write_bytes(FOREIGN_CONTENT)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", replace_temporary_file_before_fsync)

    with ArtifactCache(cache_root) as cache:
        cache.directory.ensure_model_directory()
        with pytest.raises(
            ValueError, match="temporary reference changed before publication"
        ):
            cache.references.publish_reference(REVISION)

    assert temporary_path is not None
    assert temporary_path.read_bytes() == FOREIGN_CONTENT
    assert not (refs_directory / "main").exists()
    assert temporary_descriptor >= 0
    with pytest.raises(OSError):
        os.fstat(temporary_descriptor)


def test_staging_create_file_preserves_replaced_file_on_failure(
    tmp_path: Path,
) -> None:
    """Failed staged writes preserve a foreign replacement and close descriptors."""
    cache_root = tmp_path / "cache"
    model_directory = cache_root / MODEL_CACHE_NAME
    stage_path: Path | None = None
    stage_descriptor = -1
    file_descriptor = -1

    with ArtifactCache(cache_root) as cache:
        cache.directory.ensure_model_directory()
        with (
            pytest.raises(ValueError, match="staged asset changed during write"),
            staging_directory(directory=cache.directory) as staging,
        ):
            stage_descriptor = staging._descriptor
            stage_path = model_directory / staging._name / "asset-0.part"
            with staging.create_file("asset-0.part") as stream:
                file_descriptor = stream.fileno()
                stream.write(b"old staged content")
                stage_path.unlink()
                stage_path.write_bytes(FOREIGN_CONTENT)

    assert stage_path is not None
    assert stage_path.read_bytes() == FOREIGN_CONTENT
    assert stage_descriptor >= 0
    assert file_descriptor >= 0
    with pytest.raises(OSError):
        os.fstat(stage_descriptor)
    with pytest.raises(OSError):
        os.fstat(file_descriptor)


def test_cache_exit_preserves_body_error_and_closes_both_descriptors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A model descriptor close failure must not mask the body error or leak root."""
    cache = ArtifactCache(tmp_path / "cache")
    cache.directory.ensure_model_directory()
    root_descriptor = cache.directory._root_fd
    model_descriptor = cache.directory._model_fd
    assert root_descriptor is not None
    assert model_descriptor is not None
    real_close = os.close

    def close_model_then_raise(descriptor: int) -> None:
        real_close(descriptor)
        if descriptor == model_descriptor:
            raise OSError("injected model descriptor close failure")

    monkeypatch.setattr(os, "close", close_model_then_raise)
    try:
        with pytest.raises(ValueError, match="primary cache failure") as failure, cache:
            raise ValueError("primary cache failure")

        assert failure.value.__notes__
        assert any("cleanup also failed" in note for note in failure.value.__notes__)
        with pytest.raises(OSError):
            os.fstat(model_descriptor)
        with pytest.raises(OSError):
            os.fstat(root_descriptor)
    finally:
        for descriptor in (model_descriptor, root_descriptor):
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            real_close(descriptor)


def test_staging_directory_init_fsync_failure_removes_owned_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stage init failure removes its newly created empty directory."""
    cache_root = tmp_path / "cache"
    model_directory = cache_root / MODEL_CACHE_NAME
    stage_directory_at_failure: Path | None = None
    real_fsync = os.fsync

    with ArtifactCache(cache_root) as cache:
        cache.directory.ensure_model_directory()
        model_descriptor = cache.directory._model_fd
        assert model_descriptor is not None

        def fail_after_stage_directory_creation(descriptor: int) -> None:
            nonlocal stage_directory_at_failure
            if descriptor == model_descriptor:
                candidates = list(model_directory.glob(".embedding-artifacts-*"))
                if candidates:
                    assert len(candidates) == 1
                    stage_directory_at_failure = candidates[0]
                    raise OSError("injected staging parent fsync failure")
            real_fsync(descriptor)

        monkeypatch.setattr(os, "fsync", fail_after_stage_directory_creation)
        with (
            pytest.raises(OSError, match="injected staging parent fsync failure"),
            staging_directory(directory=cache.directory),
        ):
            pytest.fail("staging must fail before yielding")

    assert stage_directory_at_failure is not None
    assert not stage_directory_at_failure.exists()
    assert not list(model_directory.glob(".embedding-artifacts-*"))


def test_publish_reference_fdopen_failure_closes_descriptor_and_removes_temp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An fdopen allocation failure leaves neither the descriptor nor owned ref temp."""
    cache_root = tmp_path / "cache"
    refs_directory = cache_root / MODEL_CACHE_NAME / "refs"
    temp_path: Path | None = None
    temp_descriptor = -1
    temp_identity: tuple[int, int] | None = None
    injected_error = MemoryError("injected fdopen allocation failure")

    def fail_before_ownership(
        descriptor: int,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal temp_descriptor, temp_identity, temp_path
        opened = os.fstat(descriptor)
        candidates = [
            path
            for path in refs_directory.glob(".main-*.tmp")
            if (entry := path.stat()).st_dev == opened.st_dev
            and entry.st_ino == opened.st_ino
        ]
        assert len(candidates) == 1
        temp_path = candidates[0]
        temp_descriptor = descriptor
        temp_identity = (opened.st_dev, opened.st_ino)
        raise injected_error

    cache = ArtifactCache(cache_root)
    try:
        with cache:
            cache.directory.ensure_model_directory()
            monkeypatch.setattr(os, "fdopen", fail_before_ownership)
            with pytest.raises(MemoryError) as failure:
                cache.references.publish_reference(REVISION)

        assert failure.value is injected_error
        assert temp_path is not None
        assert temp_identity is not None
        with pytest.raises(OSError) as closed_descriptor:
            os.fstat(temp_descriptor)
        assert closed_descriptor.value.errno == errno.EBADF
        assert not list(refs_directory.glob(".main-*.tmp"))
    finally:
        if temp_descriptor >= 0 and temp_identity is not None:
            try:
                opened = os.fstat(temp_descriptor)
            except OSError:
                pass
            else:
                if (opened.st_dev, opened.st_ino) == temp_identity:
                    os.close(temp_descriptor)
        if temp_path is not None and temp_identity is not None:
            try:
                entry = temp_path.stat()
            except OSError:
                pass
            else:
                if (entry.st_dev, entry.st_ino) == temp_identity:
                    temp_path.unlink()
