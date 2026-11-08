"""Contracts for bounded, raw managed-Markdown observations."""

from __future__ import annotations

import asyncio
import errno
import os
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import BinaryIO, TextIO

import anyio
import pytest
from pytest import MonkeyPatch

from app.obsidian.application.service.vault import (
    obsidian_raw_source_snapshot_reader as raw_source_reader,
)
from app.obsidian.application.service.vault.obsidian_vault_inventory_service import (
    ObsidianVaultInventoryService,
)
from app.obsidian.application.service.vault.obsidian_vault_operations import (
    ObsidianVaultOperations,
)
from app.obsidian.domain.entities.obsidian_raw_source_snapshot import (
    ObsidianRawSourceSnapshot,
)
from app.obsidian.domain.policies.obsidian_source_scan_policy import (
    DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY,
    ObsidianSourceScanPolicy,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


def _inventory(vault: Path) -> ObsidianVaultInventoryService:
    """Create the source owner for one temporary vault."""
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "Alexandria").mkdir(exist_ok=True)
    return ObsidianVaultInventoryService(
        ObsidianVaultConfigStore(
            default_vault_path=str(vault),
            default_alexandria_root="Alexandria",
            config_path=None,
        )
    )


def _write_source(vault: Path, relative_path: str, payload: bytes) -> Path:
    """Write one source fixture and return its absolute path."""
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_default_policy_keeps_existing_source_scan_bounds() -> None:
    """Raw and parsed source scans share the established operational ceilings."""
    assert DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY.max_notes == 4096
    assert DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY.max_entries == 10_000
    assert DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY.max_total_bytes == 64 * 1024 * 1024
    assert DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY.max_file_bytes == 8 * 1024 * 1024
    assert DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY.max_errors == 32


def test_raw_snapshot_preserves_invalid_and_unindexed_source_text(
    tmp_path: Path,
) -> None:
    """Raw integrity input includes invalid YAML and notes without index identity."""
    vault = tmp_path / "vault"
    invalid_yaml = b"---\ntags: [unterminated\nsource: true\n"
    unindexed = b"No frontmatter and no Alexandria id.\n"
    _write_source(vault, "Alexandria/Contexts/invalid.md", invalid_yaml)
    _write_source(vault, "Alexandria/Contexts/unindexed.md", unindexed)
    inventory = _inventory(vault)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.complete is True
    assert snapshot.total_bytes_read == len(invalid_yaml) + len(unindexed)
    assert {source.relative_path: source.raw_text for source in snapshot.files} == {
        "Alexandria/Contexts/invalid.md": invalid_yaml.decode("utf-8"),
        "Alexandria/Contexts/unindexed.md": unindexed.decode("utf-8"),
    }


def test_vault_operations_forwards_the_raw_source_snapshot(
    tmp_path: Path,
) -> None:
    """The Obsidian source facade exposes the bounded raw inventory contract."""
    vault = tmp_path / "vault"
    expected_text = "---\ntags: invalid-scalar\n"
    _write_source(
        vault,
        "Alexandria/Contexts/unindexed.md",
        expected_text.encode("utf-8"),
    )
    inventory = _inventory(vault)

    class _InventoryOperations(ObsidianVaultOperations):
        def __init__(self) -> None:
            self._vault_inventory_service = inventory

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await _InventoryOperations().raw_source_snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.complete is True
    assert snapshot.files[0].raw_text == expected_text


@pytest.mark.parametrize(
    ("policy", "expected_file_count"),
    [
        (
            ObsidianSourceScanPolicy(
                max_notes=1,
                max_entries=10,
                max_total_bytes=100,
                max_file_bytes=100,
                max_errors=2,
            ),
            1,
        ),
        (
            ObsidianSourceScanPolicy(
                max_notes=10,
                max_entries=1,
                max_total_bytes=100,
                max_file_bytes=100,
                max_errors=2,
            ),
            0,
        ),
    ],
)
def test_raw_snapshot_marks_note_and_entry_limits_incomplete(
    tmp_path: Path,
    policy: ObsidianSourceScanPolicy,
    expected_file_count: int,
) -> None:
    """Note and traversal-entry ceilings never return a complete prefix."""
    vault = tmp_path / "vault"
    _write_source(vault, "Alexandria/Contexts/a.md", b"a")
    _write_source(vault, "Alexandria/Contexts/b.md", b"b")
    inventory = _inventory(vault)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot(policy)

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert len(snapshot.files) == expected_file_count
    assert snapshot.total_bytes_read <= policy.max_total_bytes + 1
    assert "SOURCE_SCAN_LIMIT_EXCEEDED" in snapshot.errors


def test_raw_snapshot_bounds_aggregate_bytes_when_file_grows_after_discovery(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """The read budget uses bytes actually read, including one growth sentinel."""
    vault = tmp_path / "vault"
    first = _write_source(vault, "Alexandria/Contexts/a.md", b"1234")
    growing = _write_source(vault, "Alexandria/Contexts/b.md", b"12")
    inventory = _inventory(vault)
    policy = ObsidianSourceScanPolicy(
        max_notes=10,
        max_entries=10,
        max_total_bytes=8,
        max_file_bytes=8,
        max_errors=2,
    )
    original_read = raw_source_reader._read_bounded_source

    def grow_before_read(
        root_descriptor: int,
        relative_path: Path,
        max_bytes: int,
    ) -> bytes:
        if relative_path == Path("Alexandria/Contexts/b.md"):
            growing.write_bytes(b"12345678")
        return original_read(root_descriptor, relative_path, max_bytes)

    monkeypatch.setattr(raw_source_reader, "_read_bounded_source", grow_before_read)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot(policy)

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert tuple(source.relative_path for source in snapshot.files) == (
        str(first.relative_to(vault)),
    )
    assert snapshot.total_bytes_read == 9
    assert "SOURCE_SCAN_LIMIT_EXCEEDED" in snapshot.errors


def test_raw_snapshot_marks_per_file_growth_incomplete(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A source that grows past its own ceiling is read only through one sentinel."""
    vault = tmp_path / "vault"
    growing = _write_source(vault, "Alexandria/Contexts/growing.md", b"12")
    inventory = _inventory(vault)
    policy = ObsidianSourceScanPolicy(
        max_notes=10,
        max_entries=10,
        max_total_bytes=8,
        max_file_bytes=4,
        max_errors=2,
    )
    original_read = raw_source_reader._read_bounded_source

    def grow_before_read(
        root_descriptor: int,
        relative_path: Path,
        max_bytes: int,
    ) -> bytes:
        if relative_path == Path("Alexandria/Contexts/growing.md"):
            growing.write_bytes(b"12345678")
        return original_read(root_descriptor, relative_path, max_bytes)

    monkeypatch.setattr(raw_source_reader, "_read_bounded_source", grow_before_read)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot(policy)

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert snapshot.files == ()
    assert snapshot.total_bytes_read == policy.max_file_bytes + 1
    assert "SOURCE_SCAN_LIMIT_EXCEEDED" in snapshot.errors


def test_raw_snapshot_rejects_decode_and_open_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Decode and read errors are bounded diagnostics and make the scan incomplete."""
    vault = tmp_path / "vault"
    invalid = _write_source(vault, "Alexandria/Contexts/invalid.md", b"\xff")
    _write_source(vault, "Alexandria/Contexts/unreadable.md", b"text")
    inventory = _inventory(vault)
    original_read = raw_source_reader._read_bounded_source

    def fail_one_source(
        root_descriptor: int,
        relative_path: Path,
        max_bytes: int,
    ) -> bytes:
        if relative_path == Path("Alexandria/Contexts/unreadable.md"):
            raise PermissionError("fixture read failure")
        return original_read(root_descriptor, relative_path, max_bytes)

    monkeypatch.setattr(raw_source_reader, "_read_bounded_source", fail_one_source)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert snapshot.files == ()
    assert snapshot.total_bytes_read == invalid.stat().st_size
    assert snapshot.errors.count("SOURCE_READ_FAILED") == 2


def test_raw_snapshot_rejects_symlinks_and_nonregular_files_before_read(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Path confinement and file type checks happen before any blocking read."""
    vault = tmp_path / "vault"
    outside = _write_source(tmp_path, "outside.md", b"outside")
    linked = vault / "Alexandria" / "Contexts" / "linked.md"
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(outside)
    fifo = vault / "Alexandria" / "Contexts" / "special.md"
    os.mkfifo(fifo)
    inventory = _inventory(vault)
    original_open = Path.open
    opened: set[Path] = set()

    def record_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> BinaryIO | TextIO:
        opened.add(path)
        return original_open(
            path,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    monkeypatch.setattr(Path, "open", record_open)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert snapshot.files == ()
    assert opened == set()
    assert "PATH_SECURITY_VIOLATION" in snapshot.errors
    assert "SOURCE_READ_FAILED" in snapshot.errors


def test_raw_snapshot_rejects_leaf_symlink_installed_after_validation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A leaf replaced after validation cannot redirect a source read."""
    vault = tmp_path / "vault"
    _write_source(vault, "Alexandria/Contexts/note.md", b"inside")
    outside = _write_source(tmp_path, "outside.md", b"outside")
    inventory = _inventory(vault)
    original_validate = raw_source_reader.validate_discovered_note_path

    def replace_after_validation(
        vault_path: str | Path,
        managed_root: str | Path,
        candidate: Path,
    ) -> Path:
        validated = original_validate(vault_path, managed_root, candidate)
        validated.unlink()
        validated.symlink_to(outside)
        return validated

    monkeypatch.setattr(
        raw_source_reader,
        "validate_discovered_note_path",
        replace_after_validation,
    )

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert snapshot.files == ()
    assert snapshot.total_bytes_read == 0
    assert "SOURCE_READ_FAILED" in snapshot.errors


def test_raw_snapshot_rejects_parent_symlink_installed_after_validation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A parent replaced after validation cannot redirect a source read."""
    vault = tmp_path / "vault"
    source = _write_source(vault, "Alexandria/Contexts/note.md", b"inside")
    outside = tmp_path / "outside-contexts"
    outside.mkdir()
    (outside / source.name).write_bytes(b"outside")
    context_dir = source.parent
    moved_context_dir = context_dir.with_name("Contexts-held")
    inventory = _inventory(vault)
    original_validate = raw_source_reader.validate_discovered_note_path

    def replace_after_validation(
        vault_path: str | Path,
        managed_root: str | Path,
        candidate: Path,
    ) -> Path:
        validated = original_validate(vault_path, managed_root, candidate)
        context_dir.rename(moved_context_dir)
        context_dir.symlink_to(outside, target_is_directory=True)
        return validated

    monkeypatch.setattr(
        raw_source_reader,
        "validate_discovered_note_path",
        replace_after_validation,
    )

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot()

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert snapshot.files == ()
    assert snapshot.total_bytes_read == 0
    assert "SOURCE_READ_FAILED" in snapshot.errors


@pytest.mark.parametrize(
    "relative_path",
    [Path("../outside.md"), Path("/outside.md")],
)
def test_bounded_source_rejects_paths_outside_the_vault_root(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    """Descriptor traversal rejects parent-relative and absolute paths."""
    vault = tmp_path / "vault"
    _write_source(vault, "Alexandria/Contexts/note.md", b"inside")
    root_descriptor = os.open(
        vault.resolve(),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        with pytest.raises(OSError, match="relative to the vault root"):
            raw_source_reader._read_bounded_source(root_descriptor, relative_path, 1)
    finally:
        os.close(root_descriptor)


def test_raw_snapshot_rejects_fifo_installed_before_open_without_blocking(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A FIFO race is rejected without waiting for a writer."""
    vault = tmp_path / "vault"
    source = _write_source(vault, "Alexandria/Contexts/note.md", b"inside")
    inventory = _inventory(vault)
    original_read = raw_source_reader._read_bounded_source
    fifo_installed = Event()
    completed = Event()
    results: list[ObsidianRawSourceSnapshot] = []
    failures: list[BaseException] = []

    def replace_with_fifo(
        root_descriptor: int,
        relative_path: Path,
        max_bytes: int,
    ) -> bytes:
        source.unlink()
        os.mkfifo(source)
        fifo_installed.set()
        return original_read(root_descriptor, relative_path, max_bytes)

    monkeypatch.setattr(raw_source_reader, "_read_bounded_source", replace_with_fifo)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot()

    def run_snapshot() -> None:
        try:
            results.append(anyio.run(scenario))
        except BaseException as error:
            failures.append(error)
        finally:
            completed.set()

    worker = Thread(target=run_snapshot)
    worker.start()
    assert fifo_installed.wait(timeout=2)
    completed_without_writer = completed.wait(timeout=1)
    if not completed_without_writer:
        # A regressed blocking opener is released by a nonblocking writer.
        release_deadline = monotonic() + 2
        while not completed.is_set():
            try:
                writer_fd = os.open(source, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno != errno.ENXIO:
                    raise
                remaining = release_deadline - monotonic()
                assert remaining > 0, "FIFO reader did not reach its open"
                completed.wait(timeout=min(remaining, 0.01))
            else:
                with os.fdopen(writer_fd, "wb") as writer_stream:
                    writer_stream.write(b"fifo payload")
                break
    assert completed.wait(timeout=2)
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert failures == []
    assert completed_without_writer is True
    snapshot = results[0]
    assert snapshot.complete is False
    assert snapshot.files == ()
    assert "SOURCE_READ_FAILED" in snapshot.errors


def test_raw_snapshot_saturates_error_samples_without_becoming_complete(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """More read failures than the sample cap remain incomplete after saturation."""
    vault = tmp_path / "vault"
    sources = [
        _write_source(vault, f"Alexandria/Contexts/{index:02}.md", b"text")
        for index in range(5)
    ]
    inventory = _inventory(vault)
    policy = ObsidianSourceScanPolicy(
        max_notes=10,
        max_entries=10,
        max_total_bytes=100,
        max_file_bytes=100,
        max_errors=2,
    )
    original_read = raw_source_reader._read_bounded_source
    source_paths = {
        Path(f"Alexandria/Contexts/{index:02}.md") for index in range(len(sources))
    }

    def fail_every_source(
        root_descriptor: int,
        relative_path: Path,
        max_bytes: int,
    ) -> bytes:
        if relative_path in source_paths:
            raise OSError("fixture read failure")
        return original_read(root_descriptor, relative_path, max_bytes)

    monkeypatch.setattr(raw_source_reader, "_read_bounded_source", fail_every_source)

    async def scenario() -> ObsidianRawSourceSnapshot:
        return await inventory.raw_source_snapshot(policy)

    snapshot = anyio.run(scenario)

    assert snapshot.complete is False
    assert len(snapshot.errors) == policy.max_errors
    assert snapshot.errors == ("SOURCE_READ_FAILED", "SOURCE_READ_FAILED")


def test_raw_snapshot_io_is_responsive_and_owned_through_cancellation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Blocking source reads run off-loop and finish before cancellation escapes."""
    vault = tmp_path / "vault"
    _write_source(vault, "Alexandria/Contexts/note.md", b"content")
    inventory = _inventory(vault)
    worker_started = asyncio.Event()
    release_worker = Event()
    original_read = raw_source_reader._read_bounded_source
    loop: asyncio.AbstractEventLoop | None = None

    def block_source_open(
        root_descriptor: int,
        relative_path: Path,
        max_bytes: int,
    ) -> bytes:
        if relative_path == Path("Alexandria/Contexts/note.md"):
            if loop is None:
                raise AssertionError("event loop must be captured before reading")
            loop.call_soon_threadsafe(worker_started.set)
            if not release_worker.wait(timeout=5):
                raise TimeoutError("test did not release source read")
        return original_read(root_descriptor, relative_path, max_bytes)

    monkeypatch.setattr(raw_source_reader, "_read_bounded_source", block_source_open)

    async def scenario() -> None:
        nonlocal loop
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(inventory.raw_source_snapshot())
        try:
            async with asyncio.timeout(2):
                await worker_started.wait()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    anyio.run(scenario)
