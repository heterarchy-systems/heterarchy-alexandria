"""Apply and verify bounded Obsidian body patches."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import anyio
import anyio.to_thread

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    _validated_source_path,
)
from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path
from app.obsidian.application.notes.writing import (
    obsidian_note_persistence as source_persistence,
)
from app.obsidian.application.service.notes.obsidian_body_patch import (
    PreparedObsidianBodyPatch,
    prepare_body_patch_source,
    validate_body_patch_replacements,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianIndexStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.obsidian.domain.repositories.obsidian_index_write_repository import (
    IObsidianIndexWriteRepository,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    AtomicMarkdownCommitUnverifiedError,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_vault_path,
    safe_relative_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.operations.application.skill_contract.skill_publication_policy import (
    active_skill_path,
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
from app.shared.types.types_convert_utils import now_utc


@dataclass(frozen=True, slots=True)
class ObsidianNoteBodyPatchResult:
    """Secret-free evidence for one bounded canonical body patch."""

    relative_path: str
    note_id: str
    content_hash_before: str
    content_hash_after: str
    index_status: ObsidianIndexStatus
    body_replacement_count: int
    changed_span_count: int
    managed_content_hash_updated: bool
    source_persisted: bool
    untouched_source_bytes_preserved: bool


def body_patch_result(
    *,
    relative_path: str,
    note_id: str,
    content_hash_before: str,
    content_hash_after: str,
    index_status: ObsidianIndexStatus,
    prepared: PreparedObsidianBodyPatch,
) -> ObsidianNoteBodyPatchResult:
    """Build one secret-free outcome from verified source evidence.

    Args:
        relative_path: Validated path of the patched source.
        note_id: Stable source identity.
        content_hash_before: Rust hash before applying replacement spans.
        content_hash_after: Rust hash of committed replacement bytes.
        index_status: Committed index status.
        prepared: Validated replacement and byte-preservation evidence.

    Returns:
        The same bounded patch evidence exposed by the existing API.
    """
    return ObsidianNoteBodyPatchResult(
        relative_path=relative_path,
        note_id=note_id,
        content_hash_before=content_hash_before,
        content_hash_after=content_hash_after,
        index_status=index_status,
        body_replacement_count=prepared.body_replacement_count,
        changed_span_count=prepared.body_replacement_count
        + int(prepared.managed_content_hash_updated),
        managed_content_hash_updated=prepared.managed_content_hash_updated,
        source_persisted=True,
        untouched_source_bytes_preserved=True,
    )


class ObsidianNoteBodyPatcher:
    """Own bounded body patch CAS, durable readback and index error mapping."""

    def __init__(
        self,
        repository: IObsidianIndexWriteRepository,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        record_index_error: Callable[[ObsidianIndexError], Awaitable[None]],
    ) -> None:
        """Bind byte patches to the existing source write lifecycle.

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

    async def patch_note_body(
        self,
        *,
        path: str,
        expected_content_hash: str,
        replacements: Sequence[tuple[str, str]],
    ) -> ObsidianNoteBodyPatchResult:
        """Apply unique exact body spans without returning canonical source text.

        The request carries only replacement spans. The service owns source
        reads, raw-hash compare-and-swap, Context body-hash maintenance, atomic
        persistence and index write-through.

        Args:
            path: Managed Vault-relative Markdown path to patch.
            expected_content_hash: Required current raw-source hash.
            replacements: Bounded exact body spans and their replacement text.

        Returns:
            Patch and source-durability evidence with index status.
        """
        try:
            encoded_replacements = validate_body_patch_replacements(replacements)
        except ValueError as exc:
            raise ObsidianValidationError(
                "BODY_PATCH_INVALID: caller replacements are invalid"
            ) from exc

        async with self._index_maintenance_coordinator.operation(
            "obsidian_body_patch", wait=True
        ):
            safe_path = str(safe_relative_path(path))
            config = self._vault_config_store.current()
            try:
                vault_root = await anyio.to_thread.run_sync(
                    partial(resolve_vault_path, config.vault_path)
                )
                absolute = await anyio.to_thread.run_sync(
                    partial(
                        _validated_source_path,
                        vault_path=vault_root,
                        relative_path=safe_path,
                        alexandria_root=config.alexandria_root,
                    )
                )
                canonical_path = absolute.relative_to(vault_root).as_posix()
            except (OSError, ValueError) as exc:
                raise ObsidianValidationError(
                    "BODY_PATCH_PATH_INVALID: source path is not a managed note"
                ) from exc
            if active_skill_path(canonical_path):
                raise ObsidianValidationError(
                    "BODY_PATCH_SKILL_PATH_UNSUPPORTED: Active Skill metadata is "
                    "managed by the publication policy"
                )
            if not absolute.exists():
                raise ObsidianNotFoundError("Obsidian note not found")

            try:
                source_bytes = await anyio.to_thread.run_sync(absolute.read_bytes)
                source_text = source_bytes.decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
            content_hash_before = hash_text(source_text)
            if content_hash_before != expected_content_hash:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: expected content hash does not match",
                    current_content_hash=content_hash_before,
                )

            try:
                indexed_before = await anyio.to_thread.run_sync(
                    partial(
                        note_index_from_path,
                        path=absolute,
                        relative_path=canonical_path,
                        alexandria_root=config.alexandria_root,
                    ),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except (OSError, UnicodeError, ValueError) as exc:
                raise ObsidianValidationError(
                    "BODY_PATCH_SOURCE_INVALID: source must parse and index"
                ) from exc
            if indexed_before is None:
                raise ObsidianValidationError(
                    "BODY_PATCH_SOURCE_INVALID: source is not Alexandria-managed"
                )
            if indexed_before.source_hash != content_hash_before:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: source changed during preflight",
                    current_content_hash=indexed_before.source_hash,
                )

            try:
                prepared = await anyio.to_thread.run_sync(
                    partial(
                        prepare_body_patch_source,
                        source_bytes,
                        encoded_replacements,
                    ),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
                prepared_text = prepared.source_bytes.decode("utf-8")
            except (UnicodeError, ValueError) as exc:
                raise ObsidianValidationError(
                    "BODY_PATCH_INVALID: patched source failed parse or identity checks"
                ) from exc

            try:
                index_payload = await run_critical_sync(
                    partial(
                        source_persistence.persist_and_index,
                        absolute,
                        prepared_text,
                        canonical_path,
                        config.alexandria_root,
                        expected_source_hash=expected_content_hash,
                    ),
                )
            except ObsidianWriteConflictError:
                raise
            except AtomicMarkdownCommitUnverifiedError as exc:
                raise ObsidianValidationError(
                    "BODY_PATCH_COMMIT_UNVERIFIED: source replacement durability "
                    "could not be confirmed"
                ) from exc
            except OSError, UnicodeError, ValueError:
                return await self._after_index_failure(
                    absolute=absolute,
                    safe_path=canonical_path,
                    note_id=indexed_before.note_id,
                    original_bytes=source_bytes,
                    candidate_bytes=prepared.source_bytes,
                    content_hash_before=content_hash_before,
                    prepared=prepared,
                )

            try:
                verified_bytes = await anyio.to_thread.run_sync(absolute.read_bytes)
            except OSError as exc:
                raise ObsidianValidationError(
                    "BODY_PATCH_COMMIT_UNVERIFIED: canonical readback failed"
                ) from exc
            if verified_bytes != prepared.source_bytes:
                try:
                    current_text = verified_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    current_hash = None
                else:
                    current_hash = hash_text(current_text)
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: canonical source changed during readback",
                    current_content_hash=current_hash,
                )

            if (
                index_payload is None
                or index_payload.note_id != indexed_before.note_id
                or index_payload.relative_path != canonical_path
                or index_payload.source_hash != hash_text(prepared_text)
            ):
                return await self._after_index_failure(
                    absolute=absolute,
                    safe_path=canonical_path,
                    note_id=indexed_before.note_id,
                    original_bytes=source_bytes,
                    candidate_bytes=prepared.source_bytes,
                    content_hash_before=content_hash_before,
                    prepared=prepared,
                )

            try:
                note = await self._repository.upsert_note(index_payload)
            except ObsidianIndexWriteError:
                return await self._after_index_failure(
                    absolute=absolute,
                    safe_path=canonical_path,
                    note_id=index_payload.note_id,
                    original_bytes=source_bytes,
                    candidate_bytes=prepared.source_bytes,
                    content_hash_before=content_hash_before,
                    prepared=prepared,
                )

            return body_patch_result(
                relative_path=canonical_path,
                note_id=note.note_id,
                content_hash_before=content_hash_before,
                content_hash_after=hash_text(prepared_text),
                index_status=note.index_status,
                prepared=prepared,
            )

    async def _after_index_failure(
        self,
        *,
        absolute: Path,
        safe_path: str,
        note_id: str,
        original_bytes: bytes,
        candidate_bytes: bytes,
        content_hash_before: str,
        prepared: PreparedObsidianBodyPatch,
    ) -> ObsidianNoteBodyPatchResult:
        """Return durable-source/index-error evidence only after readback.

        Args:
            absolute: Canonical source path to inspect.
            safe_path: Validated Vault-relative path.
            note_id: Stable identity to associate with an index error.
            original_bytes: Source bytes before the patch attempt.
            candidate_bytes: Exact replacement bytes.
            content_hash_before: Source hash observed before patching.
            prepared: Validated patch metadata and preservation evidence.

        Returns:
            Patch outcome when replacement bytes are durable but the index failed.

        Raises:
            ObsidianValidationError: No durable commit can be confirmed.
            ObsidianWriteConflictError: Different bytes appeared during readback.
        """
        try:
            durable_bytes = await anyio.to_thread.run_sync(absolute.read_bytes)
        except OSError as exc:
            raise ObsidianValidationError(
                "BODY_PATCH_COMMIT_UNVERIFIED: canonical readback failed"
            ) from exc
        if durable_bytes == original_bytes:
            raise ObsidianValidationError(
                "BODY_PATCH_PERSIST_FAILED: canonical source was not changed"
            )
        if durable_bytes != candidate_bytes:
            try:
                durable_hash = hash_text(durable_bytes.decode("utf-8"))
            except UnicodeDecodeError:
                durable_hash = None
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: canonical source changed during patch",
                current_content_hash=durable_hash,
            )

        await self._record_index_error(
            ObsidianIndexError(
                note_path=safe_path,
                context_id=note_id,
                error_code=ObsidianIndexErrorCode.INDEX_WRITE_FAILED,
                error_message=(
                    "BODY_PATCH_INDEX_FAILED: canonical source persisted; "
                    "note reindex is required"
                ),
                detected_at=now_utc(),
            )
        )
        try:
            after_text = durable_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ObsidianValidationError(
                "BODY_PATCH_COMMIT_UNVERIFIED: canonical readback is not UTF-8"
            ) from exc
        return body_patch_result(
            relative_path=safe_path,
            note_id=note_id,
            content_hash_before=content_hash_before,
            content_hash_after=hash_text(after_text),
            index_status=ObsidianIndexStatus.ERROR,
            prepared=prepared,
        )
