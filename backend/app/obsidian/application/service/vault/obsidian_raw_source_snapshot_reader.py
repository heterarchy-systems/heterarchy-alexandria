"""Read a bounded raw observation of canonical managed Markdown sources."""

from __future__ import annotations

import os
import stat
from functools import partial
from pathlib import Path

from app.obsidian.domain.entities.obsidian_raw_source_snapshot import (
    ObsidianRawSourceFile,
    ObsidianRawSourceSnapshot,
)
from app.obsidian.domain.policies.obsidian_source_scan_policy import (
    DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY,
    ObsidianSourceScanPolicy,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    resolve_vault_path,
    scan_managed_markdown_paths,
    validate_discovered_note_path,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.infrastructure.critical_task import run_critical_sync


async def read_raw_source_snapshot(
    vault_path: Path,
    alexandria_root: str,
    policy: ObsidianSourceScanPolicy = DEFAULT_OBSIDIAN_SOURCE_SCAN_POLICY,
) -> ObsidianRawSourceSnapshot:
    """Read a bounded raw snapshot through the shared critical worker lane.

    The result is a bounded filesystem observation, not an atomic snapshot:
    paths and file contents may change between discovery, validation and open.
    The read limit includes one probe byte beyond a configured ceiling. Decoded
    strings and snapshot objects add allocations, so these byte bounds are not
    an RSS ceiling.

    Args:
        vault_path: Vault root captured by the owning inventory service.
        alexandria_root: Managed-root path from the same captured configuration.
        policy: Positive note, entry, byte and error-sample limits.

    Returns:
        Bounded raw source data and explicit completeness evidence.
    """
    return await run_critical_sync(
        partial(
            _read_raw_source_snapshot_sync,
            vault_path,
            alexandria_root,
            policy,
        )
    )


def _read_raw_source_snapshot_sync(
    vault_path: Path,
    alexandria_root: str,
    policy: ObsidianSourceScanPolicy,
) -> ObsidianRawSourceSnapshot:
    """Discover, validate and decode managed sources under explicit bounds."""
    try:
        vault_root = resolve_vault_path(vault_path)
        root_descriptor = os.open(
            vault_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except FileNotFoundError, NotADirectoryError:
        return _incomplete_snapshot("SOURCE_UNAVAILABLE", policy.max_errors)
    except OSError, ValueError:
        return _incomplete_snapshot("SOURCE_DISCOVERY_FAILED", policy.max_errors)

    try:
        try:
            managed_root = resolve_note_path(vault_root, alexandria_root)
            if not managed_root.exists():
                return _incomplete_snapshot("SOURCE_UNAVAILABLE", policy.max_errors)
            scan = scan_managed_markdown_paths(
                managed_root,
                managed_root=managed_root,
                max_entries=policy.max_entries,
                max_files=policy.max_notes,
                max_total_bytes=policy.max_total_bytes,
                max_file_bytes=policy.max_file_bytes,
                max_errors=policy.max_errors,
            )
        except ObsidianValidationError as error:
            return _incomplete_snapshot(
                source_validation_error_code(error),
                policy.max_errors,
            )
        except OSError, ValueError:
            return _incomplete_snapshot("SOURCE_DISCOVERY_FAILED", policy.max_errors)

        errors = list(scan.errors)
        sources: list[ObsidianRawSourceFile] = []
        total_bytes_read = 0
        complete = scan.complete
        for discovered in scan.paths:
            try:
                path = validate_discovered_note_path(
                    vault_root,
                    alexandria_root,
                    discovered,
                )
            except ObsidianValidationError as error:
                _append_scan_error(
                    errors,
                    source_validation_error_code(error),
                    policy.max_errors,
                )
                complete = False
                continue
            except OSError:
                _append_scan_error(errors, "SOURCE_READ_FAILED", policy.max_errors)
                complete = False
                continue

            try:
                relative_path = path.relative_to(vault_root)
            except ValueError:
                _append_scan_error(
                    errors,
                    "PATH_SECURITY_VIOLATION",
                    policy.max_errors,
                )
                complete = False
                continue
            if (
                relative_path.is_absolute()
                or ".." in relative_path.parts
                or not relative_path.parts
            ):
                _append_scan_error(
                    errors,
                    "PATH_SECURITY_VIOLATION",
                    policy.max_errors,
                )
                complete = False
                continue

            bytes_remaining = policy.max_total_bytes - total_bytes_read
            byte_budget = min(policy.max_file_bytes, bytes_remaining)
            try:
                raw_bytes = _read_bounded_source(
                    root_descriptor,
                    relative_path,
                    byte_budget + 1,
                )
            except OSError:
                _append_scan_error(errors, "SOURCE_READ_FAILED", policy.max_errors)
                complete = False
                continue
            total_bytes_read += len(raw_bytes)
            if (
                len(raw_bytes) > policy.max_file_bytes
                or total_bytes_read > policy.max_total_bytes
            ):
                _append_scan_error(
                    errors,
                    "SOURCE_SCAN_LIMIT_EXCEEDED",
                    policy.max_errors,
                )
                complete = False
                break
            try:
                raw_text = raw_bytes.decode("utf-8")
            except UnicodeError:
                _append_scan_error(errors, "SOURCE_READ_FAILED", policy.max_errors)
                complete = False
                continue
            sources.append(
                ObsidianRawSourceFile(
                    relative_path=str(relative_path),
                    raw_text=raw_text,
                )
            )

        return ObsidianRawSourceSnapshot(
            files=tuple(sources),
            complete=complete and not errors,
            total_bytes_read=total_bytes_read,
            errors=tuple(errors),
        )
    finally:
        os.close(root_descriptor)


def _read_bounded_source(
    root_descriptor: int,
    relative_path: Path,
    max_bytes: int,
) -> bytes:
    """Read a regular source through no-follow descriptors under the vault root."""
    parts = relative_path.parts
    if relative_path.is_absolute() or ".." in parts or not parts:
        raise OSError("Source path must stay relative to the vault root")

    directory_descriptor = os.dup(root_descriptor)
    try:
        for component in parts[:-1]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            try:
                os.close(directory_descriptor)
            except BaseException:
                os.close(next_descriptor)
                raise
            directory_descriptor = next_descriptor

        source_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_descriptor,
        )
        try:
            source = os.fdopen(source_descriptor, "rb")
        except BaseException:
            os.close(source_descriptor)
            raise
        with source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise OSError("Managed source is not a regular file")
            return source.read(max_bytes)
    finally:
        os.close(directory_descriptor)


def source_validation_error_code(error: ObsidianValidationError) -> str:
    """Map path-validation failures to bounded, secret-free scan codes."""
    if "PATH_SECURITY_VIOLATION" in str(error):
        return "PATH_SECURITY_VIOLATION"
    return "SOURCE_VALIDATION_FAILED"


def _incomplete_snapshot(
    error: str,
    max_errors: int,
) -> ObsidianRawSourceSnapshot:
    """Return an empty incomplete observation with one bounded error sample."""
    errors: list[str] = []
    _append_scan_error(errors, error, max_errors)
    return ObsidianRawSourceSnapshot(
        files=(),
        complete=False,
        total_bytes_read=0,
        errors=tuple(errors),
    )


def _append_scan_error(errors: list[str], error: str, max_errors: int) -> None:
    """Retain one error code while the bounded sample has capacity."""
    if len(errors) < max_errors:
        errors.append(error)
