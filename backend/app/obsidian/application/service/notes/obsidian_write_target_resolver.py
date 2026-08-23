"""Resolve explicit Obsidian note-write identity before canonical mutation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from app.obsidian.application.notes.obsidian_note_templates import (
    default_note_path,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
    ObsidianReindexResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_text,
    parse_markdown_document,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    safe_relative_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIdentityConflictError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
    ObsidianWriteTargetNotFoundError,
)

logger = logging.getLogger(__name__)


class ObsidianWriteTargetResolver:
    """Resolve create/update/upsert identity and compare-and-swap preconditions."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
    ) -> None:
        """Initialize resolver dependencies.

        Args:
            repository: Rebuildable PostgreSQL note index.
            vault_config_store: Runtime canonical vault location.
            reindex: Callback used to refresh stale identity lookups.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._reindex = reindex

    async def resolve(
        self,
        command: ObsidianWriteNote,
    ) -> tuple[ObsidianSaveNote, ObsidianNote | None, ObsidianWriteOperation]:
        """Resolve exact selectors and reject every ambiguity before mutation.

        Args:
            command: Explicit create, update, or upsert request.

        Returns:
            Canonical save payload, existing target if present, and write operation.

        Raises:
            ObsidianValidationError: If required selectors or title are absent.
            ObsidianIdentityConflictError: If selectors resolve to conflicting notes.
            ObsidianWriteTargetNotFoundError: If an update target does not exist.
        """
        payload = command.note
        if command.match_by is ObsidianWriteMatchBy.NOTE_ID and payload.note_id is None:
            raise ObsidianValidationError("note_id is required when match_by=note_id")
        if (
            command.match_by is ObsidianWriteMatchBy.PATH
            and payload.relative_path is None
        ):
            raise ObsidianValidationError("path is required when match_by=path")
        title = payload.title.strip()
        if not title:
            raise ObsidianValidationError("title is required")
        config = self._vault_config_store.current()
        requested_path = payload.relative_path
        resolved_path = requested_path or default_note_path(
            root=config.alexandria_root,
            note_type=payload.alexandria_type,
            title=title,
        )
        safe_path = str(safe_relative_path(resolved_path))
        absolute = resolve_note_path(config.vault_path, safe_path)
        by_path = await self._repository.get_by_path(safe_path)
        by_id = (
            None
            if payload.note_id is None
            else await self._repository.get_by_id(payload.note_id)
        )
        path_selector_relevant = (
            requested_path is not None
            or command.match_by is ObsidianWriteMatchBy.PATH
            or command.write_mode is ObsidianWriteMode.CREATE
        )
        needs_refresh = (
            path_selector_relevant and absolute.exists() and by_path is None
        ) or (payload.note_id is not None and by_id is None)
        if needs_refresh:
            await self._reindex()
            by_path = await self._repository.get_by_path(safe_path)
            by_id = (
                None
                if payload.note_id is None
                else await self._repository.get_by_id(payload.note_id)
            )

        if (
            path_selector_relevant
            and by_id is not None
            and by_path is not None
            and by_id.note_id != by_path.note_id
        ):
            self._raise_identity_conflict(command, safe_path, by_id, by_path)

        if command.write_mode is ObsidianWriteMode.CREATE:
            if by_id is not None or by_path is not None or absolute.exists():
                self._raise_identity_conflict(command, safe_path, by_id, by_path)
            return (
                replace(payload, relative_path=safe_path),
                None,
                ObsidianWriteOperation.CREATED,
            )

        target = by_id if command.match_by is ObsidianWriteMatchBy.NOTE_ID else by_path
        if (
            target is not None
            and requested_path is not None
            and target.relative_path != safe_path
        ):
            self._raise_identity_conflict(command, safe_path, by_id, by_path)
        if (
            target is not None
            and payload.note_id is not None
            and target.note_id != payload.note_id
        ):
            self._raise_identity_conflict(command, safe_path, by_id, by_path)

        if target is None and command.write_mode is ObsidianWriteMode.UPDATE:
            raise ObsidianWriteTargetNotFoundError(
                requested_note_id=payload.note_id,
                requested_path=requested_path,
            )
        if target is None:
            if by_id is not None or by_path is not None or absolute.exists():
                self._raise_identity_conflict(command, safe_path, by_id, by_path)
            return (
                replace(payload, relative_path=safe_path),
                None,
                ObsidianWriteOperation.CREATED,
            )

        return (
            replace(
                _preserve_omitted_update_fields(
                    payload,
                    existing=target,
                    provided_fields=command.provided_fields,
                ),
                note_id=target.note_id,
                relative_path=target.relative_path,
            ),
            target,
            ObsidianWriteOperation.UPDATED,
        )

    @staticmethod
    def _raise_identity_conflict(
        command: ObsidianWriteNote,
        safe_path: str,
        id_target: ObsidianNote | None,
        path_target: ObsidianNote | None,
    ) -> None:
        """Execute raise identity conflict.

        Args:
            command: Command used by this operation.
            safe_path: Safe path used by this operation.
            id_target: Id target used by this operation.
            path_target: Path target used by this operation.
        """
        raise ObsidianIdentityConflictError(
            operation=command.write_mode.value,
            requested_note_id=command.note.note_id,
            requested_path=safe_path,
            id_target_path=None if id_target is None else id_target.relative_path,
            path_target_id=None if path_target is None else path_target.note_id,
            recommended_operation=(
                "update"
                if command.write_mode is ObsidianWriteMode.CREATE
                else "resolve_identity"
            ),
        )

    @staticmethod
    def _validate_expected_content_hash(
        payload: ObsidianSaveNote,
        indexed_note: ObsidianNote | None,
        safe_path: str,
    ) -> None:
        """Reject a stale compare-and-swap token before replacing Markdown.

        Args:
            payload: Validated payload for this operation.
            indexed_note: Indexed note used by this operation.
            safe_path: Safe path used by this operation.
        """
        expected = payload.expected_content_hash
        if expected is None:
            return
        if indexed_note is None:
            raise ObsidianWriteConflictError(
                f"OBSIDIAN_WRITE_CONFLICT: note does not exist: {safe_path}"
            )
        if indexed_note.content_hash != expected:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: expected content hash does not match "
                f"the current note: {safe_path}"
            )

    def note_id_from_existing_file(self, path: Path) -> str | None:
        """Read a stable note id from an existing managed Markdown file.

        Args:
            path: Candidate Markdown path.

        Returns:
            Stable frontmatter id when safely readable.
        """
        if not path.exists() or path.is_symlink():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            document = parse_markdown_document(text)
        except ValueError:
            return None
        return frontmatter_text(document.frontmatter, "id")


def _preserve_omitted_update_fields(
    payload: ObsidianSaveNote,
    existing: ObsidianNote,
    provided_fields: frozenset[str] | None,
) -> ObsidianSaveNote:
    """Retain existing optional fields omitted at the external update boundary.

    Args:
        payload: Validated payload for this operation.
        existing: Existing used by this operation.
        provided_fields: Provided fields used by this operation.

    Returns:
        ObsidianSaveNote result produced by preserve omitted update fields.
    """
    if provided_fields is None:
        return payload
    return replace(
        payload,
        tags=payload.tags if "tags" in provided_fields else existing.tags,
        status=payload.status if "status" in provided_fields else existing.status,
        project=payload.project if "project" in provided_fields else existing.project,
        source=(
            payload.source
            if "source" in provided_fields
            else existing.source or payload.source
        ),
    )
