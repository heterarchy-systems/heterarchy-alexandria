"""Bounded single-note PostgreSQL index revalidation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import partial

import anyio
import anyio.to_thread
from typing_extensions import TypedDict

from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    _read_source_text,
    note_index_from_path,
)
from app.obsidian.application.notes.writing import (
    obsidian_note_persistence as source_persistence,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianIndexError, ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexErrorCode,
)
from app.obsidian.domain.repositories.obsidian_index_write_repository import (
    IObsidianIndexWriteRepository,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
    update_frontmatter_scalars,
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
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.types.extra_types import JSONObject, JSONPrimitive
from app.shared.types.types_convert_utils import now_utc


class ContextContentHash(TypedDict, closed=True):
    """Managed Context hash used to validate an index-only correction."""

    content_hash: str


class ObsidianNoteRevalidation:
    """Re-parse one managed note and refresh only its index row."""

    def __init__(
        self,
        repository: IObsidianIndexWriteRepository,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        record_index_error: Callable[[ObsidianIndexError], Awaitable[None]],
    ) -> None:
        """Bind bounded revalidation to existing repository/Vault ownership.

        Args:
            repository: PostgreSQL index used to commit parsed source.
            vault_config_store: Authoritative runtime Vault location.
            index_maintenance_coordinator: Existing source mutation lock owner.
            record_index_error: Best-effort owner for reindex diagnostics.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._record_index_error = record_index_error

    async def revalidate_note_index(
        self, *, path: str, expected_source_hash: str | None = None
    ) -> ObsidianNote:
        """Re-parse one note's exact source and refresh its index row.

        This is the bounded note-local alternative to a broad vault reindex:
        only the addressed note's index row changes, so a stale index-hash
        repair cannot fail on unrelated notes.

        Args:
            path: Vault-relative Markdown path of the note to revalidate.
            expected_source_hash: Exact raw source revision admitted by the plan.

        Returns:
            The refreshed authoritative note.

        Raises:
            ObsidianValidationError: When the source no longer parses or is
                missing Alexandria frontmatter, so an agent repair is needed.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_bounded_source_repair", wait=True
        ):
            safe_path = str(safe_relative_path(path))
            config = self._vault_config_store.current()
            absolute = resolve_note_path(
                vault_path=config.vault_path, relative_path=safe_path
            )
            if not absolute.exists():
                raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
            if expected_source_hash is not None:
                current_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, path=absolute, max_source_bytes=None)
                )
                if hash_text(current_text) != expected_source_hash:
                    raise ObsidianWriteConflictError(
                        "OBSIDIAN_WRITE_CONFLICT: repair source drifted from preview"
                    )
                document = parse_markdown_document(current_text)
                frontmatter = frontmatter_json(document.frontmatter)
                if (
                    frontmatter.get("alexandria_type")
                    == AlexandriaNoteType.CONTEXT.value
                    and "content_hash" in frontmatter
                ):
                    canonical_hash = context_content_hash(document.body)
                    if frontmatter["content_hash"] != canonical_hash:
                        candidate: JSONObject = dict(frontmatter)
                        candidate["content_hash"] = canonical_hash
                        project = candidate.get("project")
                        context_identity_from_frontmatter(
                            candidate,
                            project=project if isinstance(project, str) else None,
                            status=str(candidate.get("status", "active")),
                            generated_content_hash=canonical_hash,
                        )
                        hash_replacement: Mapping[str, JSONPrimitive] = dict(
                            ContextContentHash(content_hash=canonical_hash).items()
                        )
                        repaired = update_frontmatter_scalars(
                            text=current_text,
                            replacements=hash_replacement,
                        )
                        # This is a server-owned scalar repair, not a caller raw
                        # roundtrip. Reuse the source-CAS persistence primitive;
                        # the existing body and every other field stay byte exact.
                        try:
                            repaired_index = await run_critical_sync(
                                partial(
                                    source_persistence.persist_and_index,
                                    absolute,
                                    repaired,
                                    safe_path,
                                    config.alexandria_root,
                                    expected_source_hash=expected_source_hash,
                                )
                            )
                        except ValueError as exc:
                            await run_critical_sync(
                                partial(
                                    source_persistence.restore_source_if_owned,
                                    absolute=absolute,
                                    expected_document=repaired,
                                    previous_document=current_text,
                                )
                            )
                            raise ObsidianValidationError(
                                "NOTE_MANAGED_HASH_REPAIR_INVALID"
                            ) from exc
                        if repaired_index is None:
                            await run_critical_sync(
                                partial(
                                    source_persistence.restore_source_if_owned,
                                    absolute=absolute,
                                    expected_document=repaired,
                                    previous_document=current_text,
                                )
                            )
                            raise ObsidianValidationError(
                                "NOTE_MANAGED_HASH_REPAIR_INVALID"
                            )
                        return await self._repository.upsert_note(repaired_index)
            try:
                index_payload = await anyio.to_thread.run_sync(
                    partial(
                        note_index_from_path,
                        path=absolute,
                        relative_path=safe_path,
                        alexandria_root=config.alexandria_root,
                    ),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except ValueError as exc:
                raise ObsidianValidationError(
                    f"NOTE_SOURCE_INVALID: {safe_path} requires frontmatter repair: {exc}"
                ) from exc
            if index_payload is None:
                raise ObsidianValidationError(
                    f"NOTE_SOURCE_INVALID: {safe_path} is missing Alexandria frontmatter"
                )
            try:
                return await self._repository.upsert_note(index_payload)
            except ObsidianIndexWriteError as exc:
                index_error = ObsidianIndexError(
                    note_path=safe_path,
                    context_id=index_payload.note_id,
                    error_code=ObsidianIndexErrorCode.INDEX_WRITE_FAILED,
                    error_message=str(exc),
                    detected_at=now_utc(),
                )
                await self._record_index_error(index_error)
                raise ObsidianValidationError(
                    "INDEX_WRITE_FAILED: canonical Markdown was preserved for reindex"
                ) from exc
