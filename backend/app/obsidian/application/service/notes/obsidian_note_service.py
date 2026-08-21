"""Canonical Obsidian note search, read, and save service."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from app.obsidian.application.graph.diagnostics.obsidian_graph_link_renderer import (
    add_or_update_alexandria_links_section,
)
from app.obsidian.application.notes.frontmatter.obsidian_frontmatter_redaction import (
    redacted_frontmatter,
)
from app.obsidian.application.notes.frontmatter.obsidian_note_write_metadata import (
    apply_write_history,
    frontmatter_for_explicit_write,
    write_is_unchanged,
)
from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_path,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_save_policy import (
    apply_context_save_policy,
)
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.notes.obsidian_note_templates import (
    default_note_path,
    frontmatter_for_save,
)
from app.obsidian.application.service.notes.obsidian_note_service_contracts import (
    ObsidianNoteSupersedeHook,
)
from app.obsidian.application.service.notes.obsidian_write_target_resolver import (
    ObsidianWriteTargetResolver,
)
from app.obsidian.application.service.vault.obsidian_vault_lifecycle_service import (
    index_error_code,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianSearchQuery,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
    ObsidianNoteWriteResult,
    ObsidianReindexResult,
    ObsidianSearchHit,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianIndexErrorCode,
    ObsidianWriteOperation,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    render_markdown_document,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    safe_relative_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianNotFoundError,
    ObsidianValidationError,
)
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import now_utc
from app.shared.utils.secret_redaction import redact_secret_text

logger = logging.getLogger(__name__)


class ObsidianNoteService:
    """Own canonical note access, Markdown persistence, and index write-through."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
        mark_context_superseded: ObsidianNoteSupersedeHook,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
    ) -> None:
        """Create the canonical note service.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            reindex: Vault index refresh callback.
            mark_context_superseded: Context lifecycle reconciliation callback.
            index_maintenance_coordinator: Process-wide rebuildable-index write lane.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._reindex = reindex
        self._mark_context_superseded = mark_context_superseded
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._write_target_resolver = ObsidianWriteTargetResolver(
            repository=repository,
            vault_config_store=vault_config_store,
            reindex=reindex,
        )

    async def search(
        self,
        query: ObsidianSearchQuery,
        refresh: bool = False,
    ) -> list[ObsidianSearchHit]:
        """Search Obsidian notes through the PostgreSQL index.

        Args:
            query: Search filters and query text.
            refresh: Whether to re-scan the vault before querying.

        Returns:
            Ranked search hits.
        """
        if refresh:
            await self._reindex()
        return await self._repository.search(query)

    async def read_note(self, note_id: str) -> ObsidianNote:
        """Read one managed note by stable id and reload its Markdown body.

        Args:
            note_id: Stable note id from frontmatter.

        Returns:
            Authoritative note loaded from Markdown.
        """
        config = self._vault_config_store.current()
        indexed = await self._repository.get_by_id(note_id)
        if indexed is None:
            await self._reindex()
            indexed = await self._repository.get_by_id(note_id)
        if indexed is None:
            raise ObsidianNotFoundError(f"Obsidian note not found: {note_id}")
        return authoritative_note_from_path(
            vault_path=config.vault_path,
            relative_path=indexed.relative_path,
            alexandria_root=config.alexandria_root,
            indexed=indexed,
        )

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        """Read one managed note by vault-relative path.

        Args:
            relative_path: Vault-relative Markdown path.

        Returns:
            Authoritative note loaded from Markdown.
        """
        config = self._vault_config_store.current()
        safe_path = str(safe_relative_path(relative_path))
        indexed = await self._repository.get_by_path(safe_path)
        if indexed is None:
            await self._reindex()
            indexed = await self._repository.get_by_path(safe_path)
        if indexed is None:
            raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
        return authoritative_note_from_path(
            vault_path=config.vault_path,
            relative_path=safe_path,
            alexandria_root=config.alexandria_root,
            indexed=indexed,
        )

    async def save_note(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Create or replace one Alexandria-managed Markdown note.

        Args:
            payload: Save request with body and metadata.

        Returns:
            Saved note loaded through the index.
        """
        async with self._index_maintenance_coordinator.write_operation(
            "obsidian_note_write"
        ):
            note, _ = await self._save_note_serialized(payload)
            return note

    async def write_note(
        self,
        command: ObsidianWriteNote,
    ) -> ObsidianNoteWriteResult:
        """Execute an explicit create, update, or upsert without identity guessing.

        Args:
            command: Value supplied to write_note.

        Returns:
            Result produced by write_note.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_explicit_note_write",
            wait=True,
        ):
            (
                payload,
                existing,
                expected_operation,
            ) = await self._write_target_resolver.resolve(command)
            note, mutated = await self._save_note_serialized(
                payload,
                existing_note=existing,
                frontmatter_mode=command.frontmatter_mode,
            )
        operation = expected_operation if mutated else ObsidianWriteOperation.UNCHANGED
        return ObsidianNoteWriteResult(
            operation=operation,
            write_mode=command.write_mode,
            match_by=command.match_by,
            note=note,
            storage_status="stored" if mutated else "unchanged",
            metadata_status="indexed",
            fts_status="indexed",
            graph_edge_index_status="indexed",
            graph_projection_status="stale" if mutated else "unknown",
            reindex_required=mutated,
        )

    async def _save_note_serialized(
        self,
        payload: ObsidianSaveNote,
        existing_note: ObsidianNote | None = None,
        frontmatter_mode: ObsidianFrontmatterMode | None = None,
    ) -> tuple[ObsidianNote, bool]:
        """Save one note while serializing canonical read-check-replace writes."""
        config = self._vault_config_store.current()
        title = payload.title.strip()
        if not title:
            raise ObsidianValidationError("title is required")
        redaction = redact_secret_text(payload.body)
        if redaction.blocked:
            raise ObsidianValidationError("high-risk secret content cannot be saved")
        frontmatter_payload, frontmatter_warnings = redacted_frontmatter(
            payload.frontmatter
        )
        payload = replace(payload, frontmatter=frontmatter_payload)
        relative_path = payload.relative_path or default_note_path(
            root=config.alexandria_root,
            note_type=payload.alexandria_type,
            title=title,
        )
        safe_path = str(safe_relative_path(relative_path))
        absolute = resolve_note_path(config.vault_path, safe_path)
        indexed_note = await self._repository.get_by_path(safe_path)
        self._write_target_resolver._validate_expected_content_hash(
            payload=payload,
            indexed_note=indexed_note,
            safe_path=safe_path,
        )
        if (
            payload.note_id is not None
            and indexed_note is not None
            and indexed_note.note_id != payload.note_id
        ):
            raise ObsidianValidationError(
                f"Obsidian path is already indexed with a different id: {safe_path}"
            )
        note_id = (
            payload.note_id
            or (None if indexed_note is None else indexed_note.note_id)
            or self._write_target_resolver.note_id_from_existing_file(absolute)
            or new_uuid()
        )
        id_match = await self._repository.get_by_id(note_id)
        if id_match is not None and id_match.relative_path != safe_path:
            raise ObsidianValidationError(
                f"DUPLICATE_CONTEXT_ID: {note_id} is already used by "
                f"{id_match.relative_path}"
            )
        absolute.parent.mkdir(parents=True, exist_ok=True)
        warnings = [*redaction.warnings, *frontmatter_warnings]
        if frontmatter_mode is None:
            frontmatter = frontmatter_for_save(
                payload,
                note_id=note_id,
                title=title,
                redaction_warnings=warnings,
            )
        else:
            frontmatter = frontmatter_for_explicit_write(
                payload,
                note_id=note_id,
                title=title,
                existing=existing_note,
                mode=frontmatter_mode,
                redaction_warnings=warnings,
            )
        body = add_or_update_alexandria_links_section(
            redaction.redacted_content,
            frontmatter,
        )
        if (
            frontmatter_mode is not None
            and existing_note is not None
            and write_is_unchanged(
                existing=existing_note,
                desired_frontmatter=frontmatter,
                desired_body=body,
            )
        ):
            return existing_note, False
        if frontmatter_mode is not None:
            frontmatter = apply_write_history(
                frontmatter,
                existing=existing_note,
                body=body,
            )
        supersedes_context_id: str | None = None
        if payload.alexandria_type is AlexandriaNoteType.CONTEXT:
            policy = await apply_context_save_policy(
                payload,
                note_id,
                frontmatter,
                body,
                self._repository,
            )
            if policy.duplicate is not None:
                return policy.duplicate, False
            frontmatter = policy.frontmatter
            supersedes_context_id = policy.supersedes_context_id
        document = render_markdown_document(frontmatter, body)
        atomic_write_markdown(absolute, document)
        index_payload = note_index_from_path(
            absolute,
            safe_path,
            alexandria_root=config.alexandria_root,
        )
        if index_payload is None:
            raise ObsidianValidationError(
                "saved note is missing Alexandria frontmatter"
            )
        try:
            note = await self._repository.upsert_note(index_payload)
        except ObsidianIndexWriteError as exc:
            index_error = ObsidianIndexError(
                note_path=safe_path,
                context_id=note_id,
                error_code=ObsidianIndexErrorCode.INDEX_WRITE_FAILED,
                error_message=str(exc),
                detected_at=now_utc(),
            )
            await self._record_index_error_best_effort(index_error)
            raise ObsidianValidationError(
                "INDEX_WRITE_FAILED: canonical Markdown was preserved for reindex"
            ) from exc
        if (
            payload.alexandria_type is AlexandriaNoteType.CONTEXT
            and supersedes_context_id is not None
        ):
            try:
                await self._mark_context_superseded(
                    superseded_context_id=supersedes_context_id,
                    replacement_context_id=note.note_id,
                )
            except (OSError, ObsidianValidationError) as exc:
                index_error = ObsidianIndexError(
                    note_path=safe_path,
                    context_id=note.note_id,
                    error_code=index_error_code(exc),
                    error_message=str(exc),
                    detected_at=now_utc(),
                )
                await self._record_index_error_best_effort(index_error)
                raise ObsidianValidationError(
                    "INDEX_WRITE_FAILED: replacement Markdown was preserved for "
                    "reindex reconciliation"
                ) from exc
        return note, True

    def note_id_from_existing_file(self, path: Path) -> str | None:
        """Read a stable note id from an existing managed Markdown file.

        Args:
            path: Candidate Markdown path.

        Returns:
            Stable frontmatter id when safely readable.
        """
        return self._write_target_resolver.note_id_from_existing_file(path)

    async def _record_index_error_best_effort(
        self,
        index_error: ObsidianIndexError,
    ) -> None:
        """Persist diagnostics without replacing the canonical write failure.

        Error persistence uses the same rebuildable PostgreSQL index. If that
        secondary recovery write also fails, the original domain error remains
        authoritative and the canonical Markdown stays available for reindex.
        """
        try:
            await self._repository.record_index_error(index_error)
        except Exception:
            logger.exception(
                "failed to persist Obsidian index error",
                extra={
                    "note_path": index_error.note_path,
                    "index_error_code": index_error.error_code.value,
                },
            )
