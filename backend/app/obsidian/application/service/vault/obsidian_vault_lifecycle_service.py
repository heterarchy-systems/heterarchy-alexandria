"""Obsidian vault configuration, initialization, and indexing lifecycle."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.obsidian.application.notes.lifecycle.obsidian_context_reindex_manifest import (
    ContextReindexCandidate,
    ContextReindexManifestValidator,
    supersedes_context_id,
)
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.notes.obsidian_note_templates import (
    default_folders,
    start_here_body,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianVaultSettingsUpdate,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianReindexResult,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexErrorCode,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.paths import (
    canonical_relative_path,
    discover_managed_markdown_paths,
    resolve_note_path,
    validate_discovered_note_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfig,
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianValidationError,
)
from app.shared.types.types_convert_utils import now_utc


@dataclass(slots=True)
class _ReindexDiagnostics:
    """Mutable accumulator for per-note errors collected during one reindex run."""

    errors: list[str] = field(default_factory=list)
    details: list[ObsidianIndexError] = field(default_factory=list)


# protocol-contract: structural-seam
class ObsidianLifecycleReadHook(Protocol):
    """Read one note by vault-relative path."""

    async def __call__(self, relative_path: str) -> ObsidianNote:
        """Read one note.

        Args:
            relative_path: Vault-relative note path.

        Returns:
            Canonical indexed note.
        """


# protocol-contract: structural-seam
class ObsidianLifecycleSaveHook(Protocol):
    """Persist one note through the canonical save path."""

    async def __call__(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Save one note.

        Args:
            payload: Canonical save command.

        Returns:
            Persisted and indexed note.
        """


# protocol-contract: structural-seam
class ObsidianMarkSupersededHook(Protocol):
    """Reconcile a superseded Context during reindex."""

    async def __call__(
        self,
        superseded_context_id: str,
        replacement_context_id: str,
    ) -> None:
        """Mark one Context as superseded.

        Args:
            superseded_context_id: Context being replaced.
            replacement_context_id: Canonical replacement Context.
        """


class ObsidianVaultLifecycleService:
    """Own vault settings, bootstrap, status, and rebuildable index lifecycle."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        context_reindex_manifest_validator: ContextReindexManifestValidator,
        vault_config_store: ObsidianVaultConfigStore,
        save_note: ObsidianLifecycleSaveHook,
        read_note_by_path: ObsidianLifecycleReadHook,
        note_id_from_existing_file: Callable[[Path], str | None],
        mark_context_superseded: ObsidianMarkSupersededHook,
        context_reindex_hook: Callable[[], Awaitable[None]] | None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
    ) -> None:
        """Create the vault lifecycle service.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            context_reindex_manifest_validator: Cross-note manifest validation authority.
            vault_config_store: Runtime vault location provider.
            save_note: Canonical note save callback.
            read_note_by_path: Canonical note read callback.
            note_id_from_existing_file: Safe frontmatter identifier reader.
            mark_context_superseded: Context lifecycle reconciliation callback.
            context_reindex_hook: Optional Context RAG reindex callback.
            index_maintenance_coordinator: Index maintenance coordinator used by this operation.
        """
        self._repository = repository
        self._context_reindex_manifest_validator = context_reindex_manifest_validator
        self._vault_config_store = vault_config_store
        self._save_note = save_note
        self._read_note_by_path = read_note_by_path
        self._note_id_from_existing_file = note_id_from_existing_file
        self._mark_context_superseded = mark_context_superseded
        self._context_reindex_hook = context_reindex_hook
        self._index_maintenance_coordinator = index_maintenance_coordinator

    async def status(self) -> ObsidianVaultStatus:
        """Return local Obsidian vault and index status.

        Returns:
            Current vault and index status.
        """
        config = self._vault_config_store.current()
        indexed, stale, errors = await self._repository.count_by_status()
        index_errors = await self._repository.list_index_errors()
        root = _root_path(config)
        return ObsidianVaultStatus(
            vault_path=str(config.vault_path),
            alexandria_root=config.alexandria_root,
            vault_exists=config.vault_path.exists(),
            alexandria_root_exists=root.exists(),
            indexed_notes=indexed,
            stale_notes=stale,
            error_notes=errors,
            index_errors=tuple(index_errors),
        )

    async def configure(
        self,
        payload: ObsidianVaultSettingsUpdate,
    ) -> ObsidianVaultStatus:
        """Change the runtime Obsidian vault destination.

        Args:
            payload: Vault settings update request.

        Returns:
            Current vault and index status after applying settings.
        """
        config = self._vault_config_store.normalized(
            vault_path=payload.vault_path,
            alexandria_root=payload.alexandria_root,
        )
        if payload.initialize:
            _ensure_vault_layout(config)
        self._vault_config_store.save(config)
        if payload.initialize:
            await self.initialize()
        if payload.reindex:
            await self.reindex()
        return await self.status()

    async def initialize(self) -> ObsidianNote:
        """Create the managed Obsidian folder layout and START_HERE note.

        Returns:
            The canonical START_HERE note.
        """
        config = self._vault_config_store.current()
        _ensure_vault_layout(config)
        start_path = f"{config.alexandria_root}/START_HERE.md"
        absolute = resolve_note_path(config.vault_path, start_path)
        if not absolute.exists():
            return await self._save_note(
                ObsidianSaveNote(
                    note_id="alexandria_start_here",
                    title="Alexandria START HERE",
                    body=start_here_body(),
                    alexandria_type=AlexandriaNoteType.CONTEXT,
                    relative_path=start_path,
                    tags=("alexandria", "start-here"),
                    status="active",
                    source="heterarchy-alexandria",
                    frontmatter={"kind": "project_context", "scope": "global"},
                )
            )
        await self.reindex()
        return await self._read_note_by_path(start_path)

    async def reindex(self) -> ObsidianReindexResult:
        """Scan managed Markdown notes and rebuild changed index rows.

        Returns:
            Reindex summary with counts and warnings.
        """
        async with self._index_maintenance_coordinator.operation("vault_reindex"):
            return await self._reindex_serialized()

    async def _reindex_serialized(self) -> ObsidianReindexResult:
        """Run one vault scan while the shared maintenance lease is held.

        Returns:
            ObsidianReindexResult result produced by reindex serialized.
        """
        config = self._vault_config_store.current()
        root = _root_path(config)
        if not root.exists():
            return ObsidianReindexResult(
                files_seen=0,
                files_indexed=0,
                files_skipped=0,
                stale_marked=await self._repository.mark_missing_stale(set()),
                errors=("Alexandria Obsidian root does not exist",),
            )
        files_seen = 0
        files_skipped = 0
        skip_reasons: dict[str, int] = {}
        diagnostics = _ReindexDiagnostics()
        seen_paths: set[str] = set()
        candidates: list[ContextReindexCandidate] = []
        discovered_paths = discover_managed_markdown_paths(root)
        paths_by_logical_identity: dict[str, list[Path]] = {}
        for path in discovered_paths:
            physical_relative_path = str(path.relative_to(config.vault_path))
            logical_relative_path = canonical_relative_path(physical_relative_path)
            paths_by_logical_identity.setdefault(logical_relative_path, []).append(path)
        colliding_paths = {
            relative_path
            for relative_path, physical_paths in paths_by_logical_identity.items()
            if len(physical_paths) > 1
        }
        for path in discovered_paths:
            files_seen += 1
            relative_path = str(path.relative_to(config.vault_path))
            logical_relative_path = canonical_relative_path(relative_path)
            if logical_relative_path in colliding_paths:
                await self._record_reindex_error(
                    relative_path,
                    self._note_id_from_existing_file(path),
                    ObsidianValidationError(
                        "CANONICAL_PATH_COLLISION: multiple physical Markdown "
                        f"paths normalize to {relative_path}"
                    ),
                    diagnostics,
                )
                continue
            seen_paths.add(relative_path)
            try:
                validated_path = validate_discovered_note_path(
                    config.vault_path,
                    config.alexandria_root,
                    path,
                )
                payload = note_index_from_path(
                    validated_path,
                    relative_path,
                    alexandria_root=config.alexandria_root,
                )
                if payload is None:
                    await self._repository.clear_index_error(relative_path)
                    files_skipped += 1
                    skip_reasons["missing_alexandria_frontmatter"] = (
                        skip_reasons.get("missing_alexandria_frontmatter", 0) + 1
                    )
                    continue
                candidates.append(
                    ContextReindexCandidate(path=validated_path, payload=payload)
                )
            except (
                OSError,
                ValueError,
                ObsidianIndexWriteError,
                ObsidianValidationError,
            ) as exc:
                await self._record_reindex_error(
                    relative_path,
                    self._note_id_from_existing_file(path),
                    exc,
                    diagnostics,
                )
        manifest = self._context_reindex_manifest_validator.validate(candidates)
        for issue in manifest.issues:
            await self._record_reindex_error(
                issue.relative_path,
                issue.context_id,
                ValueError(issue.message),
                diagnostics,
            )
        indexed_candidates: list[ContextReindexCandidate] = []
        for candidate in manifest.candidates:
            try:
                await self._repository.upsert_note(candidate.payload)
                indexed_candidates.append(candidate)
            except ObsidianIndexWriteError as exc:
                await self._record_reindex_error(
                    candidate.payload.relative_path,
                    candidate.payload.note_id,
                    exc,
                    diagnostics,
                )
        successfully_reconciled: list[ContextReindexCandidate] = []
        for candidate in indexed_candidates:
            superseded_context_id = supersedes_context_id(candidate.payload)
            if superseded_context_id is None:
                successfully_reconciled.append(candidate)
                continue
            try:
                await self._mark_context_superseded(
                    superseded_context_id=superseded_context_id,
                    replacement_context_id=candidate.payload.note_id,
                )
                successfully_reconciled.append(candidate)
            except (OSError, ObsidianValidationError) as exc:
                await self._record_reindex_error(
                    candidate.payload.relative_path,
                    candidate.payload.note_id,
                    exc,
                    diagnostics,
                )
        stale_marked = await self._repository.mark_missing_stale(seen_paths)
        edge_targets_resolved = await self._repository.resolve_edge_targets()
        if self._context_reindex_hook is not None:
            await self._context_reindex_hook()
        return ObsidianReindexResult(
            files_seen=files_seen,
            files_indexed=len(successfully_reconciled),
            files_skipped=files_skipped,
            stale_marked=stale_marked,
            errors=tuple(diagnostics.errors),
            error_details=tuple(diagnostics.details),
            skip_reasons=skip_reasons,
            edge_targets_resolved=edge_targets_resolved,
        )

    async def _record_reindex_error(
        self,
        relative_path: str,
        context_id: str | None,
        error: OSError | ValueError | ObsidianIndexWriteError | ObsidianValidationError,
        diagnostics: _ReindexDiagnostics,
    ) -> None:
        """Persist and append one structured per-note reindex failure.

        Args:
            relative_path: Relative path used by this operation.
            context_id: Identifier for context.
            error: Error value being processed.
            diagnostics: Diagnostics used by this operation.
        """
        error_code = index_error_code(error)
        safe_message = _safe_index_error_message(error_code)
        detail = ObsidianIndexError(
            note_path=relative_path,
            context_id=context_id,
            error_code=error_code,
            error_message=safe_message,
            detected_at=now_utc(),
        )
        await self._repository.record_index_error(detail)
        diagnostics.details.append(detail)
        diagnostics.errors.append(
            f"{relative_path}: {detail.error_code.value}: {safe_message}"
        )


def _root_path(config: ObsidianVaultConfig) -> Path:
    """Execute root path.

    Args:
        config: Typed configuration used by this operation.

    Returns:
        Path result produced by root path.
    """
    return resolve_note_path(config.vault_path, config.alexandria_root)


def _ensure_vault_layout(config: ObsidianVaultConfig) -> None:
    """Ensure vault layout.

    Args:
        config: Typed configuration used by this operation.
    """
    for folder in default_folders(config.alexandria_root):
        resolve_note_path(config.vault_path, folder).mkdir(parents=True, exist_ok=True)


def index_error_code(
    error: OSError | ValueError | ObsidianIndexWriteError | ObsidianValidationError,
) -> ObsidianIndexErrorCode:
    """Map one indexing failure to its stable error code.

    Args:
        error: Indexing or validation failure.

    Returns:
        Stable public error code.
    """
    message = str(error)
    message_prefix = message.partition(":")[0]
    try:
        return ObsidianIndexErrorCode(message_prefix)
    except ValueError:
        for error_code in ObsidianIndexErrorCode:
            if error_code.value in message:
                return error_code
        if isinstance(error, OSError):
            return ObsidianIndexErrorCode.SOURCE_READ_FAILED
        if isinstance(error, ObsidianIndexWriteError):
            return ObsidianIndexErrorCode.INDEX_WRITE_FAILED
        return ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR


def _safe_index_error_message(error_code: ObsidianIndexErrorCode) -> str:
    """Execute safe index error message.

    Args:
        error_code: Error code used by this operation.

    Returns:
        str result produced by safe index error message.
    """
    if error_code is ObsidianIndexErrorCode.INDEX_WRITE_FAILED:
        return "Rebuildable index write failed"
    if error_code is ObsidianIndexErrorCode.SOURCE_READ_FAILED:
        return "Canonical Markdown source could not be read"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_SECRET_DETECTED:
        return "Frontmatter contains a secret-like field"
    if error_code is ObsidianIndexErrorCode.PATH_SECURITY_VIOLATION:
        return "Managed note path failed security validation"
    if error_code in (
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_ID,
        ObsidianIndexErrorCode.DUPLICATE_CONTEXT_CONTENT,
    ):
        return "Context identity conflicts with another managed note"
    if error_code is ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR:
        return "Markdown frontmatter could not be validated"
    return "Context frontmatter failed validation"
