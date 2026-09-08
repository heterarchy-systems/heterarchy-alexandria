"""Vault inventory and path-search application service."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import anyio

from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianNoteIndex,
    ObsidianVaultInventoryRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianVaultInventoryItem,
    ObsidianVaultSourceSnapshot,
)
from app.obsidian.infrastructure.markdown.paths import (
    discover_managed_markdown_paths,
    resolve_note_path,
    scan_managed_markdown_paths,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError

DEFAULT_SOURCE_SCAN_MAX_ENTRIES = 10_000
DEFAULT_SOURCE_SCAN_MAX_TOTAL_BYTES = 64 * 1024 * 1024
DEFAULT_SOURCE_SCAN_MAX_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_SOURCE_SCAN_MAX_ERRORS = 32


class ObsidianVaultInventoryService:
    """Inventory and search managed Markdown paths without using the PostgreSQL index."""

    def __init__(self, vault_config_store: ObsidianVaultConfigStore) -> None:
        """Create the inventory service.

        Args:
            vault_config_store: Runtime vault location provider.
        """
        self._vault_config_store = vault_config_store

    async def inventory(
        self,
        request: ObsidianVaultInventoryRequest,
    ) -> list[ObsidianVaultInventoryItem]:
        """Inventory managed Markdown notes under a vault-relative scope.

        Args:
            request: Inventory request with optional scope path.

        Returns:
            Managed note inventory items sorted by path.
        """
        config = self._vault_config_store.current()
        scope = _scope_path(
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
            scope_path=request.scope_path,
        )
        if not scope.exists():
            return []
        items: list[ObsidianVaultInventoryItem] = []
        managed_root = resolve_note_path(config.vault_path, config.alexandria_root)
        for discovered in _markdown_paths(scope, managed_root=managed_root):
            path = validate_discovered_note_path(
                config.vault_path,
                config.alexandria_root,
                discovered,
            )
            relative_path = str(path.relative_to(config.vault_path))
            payload = note_index_from_path(
                path,
                relative_path,
                alexandria_root=config.alexandria_root,
            )
            if payload is None:
                continue
            items.append(
                ObsidianVaultInventoryItem(
                    note_id=payload.note_id,
                    relative_path=payload.relative_path,
                    alexandria_type=payload.alexandria_type,
                    title=payload.title,
                    status=payload.status,
                    tags=tuple(payload.tags),
                    project=payload.project,
                    size_bytes=payload.size_bytes,
                    modified_at=payload.modified_at,
                )
            )
        return items

    async def managed_markdown_paths(self) -> list[str]:
        """List every managed Markdown source, including invalid notes.

        Returns:
            Vault-relative, path-confined Markdown source paths.
        """
        config = self._vault_config_store.current()
        root = _scope_path(
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
            scope_path=None,
        )
        if not root.exists():
            return []
        relative_paths: list[str] = []
        for discovered in _markdown_paths(root, managed_root=root):
            path = validate_discovered_note_path(
                config.vault_path,
                config.alexandria_root,
                discovered,
            )
            relative_paths.append(str(path.relative_to(config.vault_path)))
        return relative_paths

    async def source_snapshot(
        self,
        max_notes: int,
        *,
        max_entries: int = DEFAULT_SOURCE_SCAN_MAX_ENTRIES,
        max_total_bytes: int = DEFAULT_SOURCE_SCAN_MAX_TOTAL_BYTES,
        max_file_bytes: int = DEFAULT_SOURCE_SCAN_MAX_FILE_BYTES,
        max_errors: int = DEFAULT_SOURCE_SCAN_MAX_ERRORS,
    ) -> ObsidianVaultSourceSnapshot:
        """Read a bounded source snapshot without touching the rebuildable index.

        Filesystem discovery reuses the existing managed-path scanner. The
        ``max_notes`` ceiling bounds canonical Markdown parsing and marks the
        snapshot incomplete when discovery finds more candidates than the
        caller allowed. A snapshot with any source error is also incomplete;
        callers must not infer uniqueness or absence from it.

        Args:
            max_notes: Maximum number of discovered Markdown files to parse.
            max_entries: Maximum filesystem entries traversed.
            max_total_bytes: Maximum aggregate Markdown bytes observed.
            max_file_bytes: Maximum bytes read from one Markdown source.
            max_errors: Maximum bounded source error codes retained.

        Returns:
            Typed source snapshot with completeness and safe error codes.
        """
        if (
            min(
                max_notes,
                max_entries,
                max_total_bytes,
                max_file_bytes,
                max_errors,
            )
            <= 0
        ):
            raise ObsidianValidationError(
                "source snapshot limits must be greater than zero"
            )
        config = self._vault_config_store.current()
        return await anyio.to_thread.run_sync(
            partial(
                _source_snapshot_sync,
                config.vault_path,
                config.alexandria_root,
                max_notes,
                max_entries,
                max_total_bytes,
                max_file_bytes,
                max_errors,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def search_paths(
        self,
        query: str,
        scope_path: str | None = None,
    ) -> list[ObsidianVaultInventoryItem]:
        """Search inventoried paths and note metadata without relying on FTS.

        Args:
            query: Keyword/path fragment to find.
            scope_path: Optional vault-relative scope.

        Returns:
            Matching inventory items.
        """
        needle = query.casefold().strip()
        if not needle:
            raise ObsidianValidationError("query is required")
        items = await self.inventory(
            ObsidianVaultInventoryRequest(scope_path=scope_path)
        )
        return [item for item in items if _inventory_item_matches(item, needle)]


def _scope_path(
    vault_path: Path,
    alexandria_root: str,
    scope_path: str | None,
) -> Path:
    """Execute scope path.

    Args:
        vault_path: Vault path used by this operation.
        alexandria_root: Alexandria root used by this operation.
        scope_path: Scope path used by this operation.

    Returns:
        Path result produced by scope path.
    """
    scope = alexandria_root if scope_path is None else scope_path
    return resolve_note_path(vault_path, scope)


def _markdown_paths(scope: Path, managed_root: Path) -> list[Path]:
    """Execute markdown paths.

    Args:
        scope: Scope used by this operation.
        managed_root: Managed root used by this operation.

    Returns:
        list[Path] result produced by markdown paths.
    """
    return discover_managed_markdown_paths(scope, managed_root=managed_root)


def _source_snapshot_sync(
    vault_path: Path,
    alexandria_root: str,
    max_notes: int,
    max_entries: int,
    max_total_bytes: int,
    max_file_bytes: int,
    max_errors: int,
) -> ObsidianVaultSourceSnapshot:
    """Discover and parse one bounded source snapshot in one worker."""
    root = _scope_path(
        vault_path=vault_path,
        alexandria_root=alexandria_root,
        scope_path=None,
    )
    if not root.exists():
        return ObsidianVaultSourceSnapshot(
            notes=(),
            complete=False,
            scanned_paths=0,
            errors=("SOURCE_UNAVAILABLE",),
        )
    managed_root = resolve_note_path(vault_path, alexandria_root)
    scan = scan_managed_markdown_paths(
        root,
        managed_root=managed_root,
        max_entries=max_entries,
        max_files=max_notes,
        max_total_bytes=max_total_bytes,
        max_file_bytes=max_file_bytes,
        max_errors=max_errors,
    )
    errors = list(scan.errors)
    bounded_paths = scan.paths
    notes: list[ObsidianNoteIndex] = []
    for discovered in bounded_paths:
        try:
            path = validate_discovered_note_path(
                vault_path,
                alexandria_root,
                discovered,
            )
            relative_path = str(path.relative_to(vault_path))
            payload = note_index_from_path(
                path,
                relative_path,
                alexandria_root=alexandria_root,
                max_source_bytes=max_file_bytes,
            )
        except ObsidianValidationError as exc:
            _append_source_error(errors, _source_validation_error_code(exc), max_errors)
            continue
        except (OSError, UnicodeError):
            _append_source_error(errors, "SOURCE_READ_FAILED", max_errors)
            continue
        except ValueError as exc:
            _append_source_error(
                errors,
                (
                    "SOURCE_SCAN_LIMIT_EXCEEDED"
                    if "SOURCE_SCAN_LIMIT_EXCEEDED" in str(exc)
                    else "FRONTMATTER_PARSE_ERROR"
                ),
                max_errors,
            )
            continue
        if payload is not None:
            notes.append(payload)
    return ObsidianVaultSourceSnapshot(
        notes=tuple(notes),
        complete=scan.complete and not errors,
        scanned_paths=len(bounded_paths),
        errors=tuple(errors),
        entries_seen=scan.entries_seen,
        total_bytes=scan.total_bytes,
    )


def _source_validation_error_code(error: ObsidianValidationError) -> str:
    """Map source validation failures to safe, stable snapshot codes."""
    if "PATH_SECURITY_VIOLATION" in str(error):
        return "PATH_SECURITY_VIOLATION"
    return "SOURCE_VALIDATION_FAILED"


def _append_source_error(errors: list[str], error: str, max_errors: int) -> None:
    """Retain bounded source diagnostics without unbounded error growth."""
    if len(errors) < max_errors:
        errors.append(error)


def _inventory_item_matches(
    item: ObsidianVaultInventoryItem,
    needle: str,
) -> bool:
    """Execute inventory item matches.

    Args:
        item: Item being processed.
        needle: Needle used by this operation.

    Returns:
        Whether inventory item matches.
    """
    haystack = "\n".join(
        [
            item.note_id,
            item.relative_path,
            item.title,
            item.alexandria_type.value,
            item.status,
            item.project or "",
            " ".join(item.tags),
        ]
    ).casefold()
    return needle in haystack
