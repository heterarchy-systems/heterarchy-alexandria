"""Vault inventory and path-search application service."""

from __future__ import annotations

from pathlib import Path

from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianVaultInventoryRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultInventoryItem
from app.obsidian.infrastructure.markdown.paths import (
    discover_managed_markdown_paths,
    resolve_note_path,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError


class ObsidianVaultInventoryService:
    """Inventory and search managed Markdown paths without using the PostgreSQL index."""

    def __init__(self, *, vault_config_store: ObsidianVaultConfigStore) -> None:
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

    async def search_paths(
        self,
        *,
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
    *,
    vault_path: Path,
    alexandria_root: str,
    scope_path: str | None,
) -> Path:
    scope = alexandria_root if scope_path is None else scope_path
    return resolve_note_path(vault_path, scope)


def _markdown_paths(scope: Path, *, managed_root: Path) -> list[Path]:
    return discover_managed_markdown_paths(scope, managed_root=managed_root)


def _inventory_item_matches(
    item: ObsidianVaultInventoryItem,
    needle: str,
) -> bool:
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
