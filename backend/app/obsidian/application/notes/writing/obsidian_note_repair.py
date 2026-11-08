"""Repair raw and parsed Obsidian note frontmatter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial

import anyio
import anyio.to_thread

from app.obsidian.application.notes.obsidian_note_indexer import _read_source_text
from app.obsidian.application.notes.writing import (
    obsidian_note_persistence as source_persistence,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianFrontmatterRepairResult,
    ObsidianIndexError,
    ObsidianNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianIndexErrorCode,
)
from app.obsidian.domain.event_enum.obsidian_note_write_enums import (
    RedactionPlaceholder,
    ServerOwnedFrontmatterField,
)
from app.obsidian.domain.repositories.obsidian_index_write_repository import (
    IObsidianIndexWriteRepository,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    parse_markdown_document,
    render_frontmatter_block,
    split_frontmatter_region,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    safe_relative_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.operations.application.skill_contract.skill_publication_policy import (
    SkillPublicationPolicy,
    active_skill_path,
    default_skill_publication_policy,
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
from app.shared.types.extra_types import JSONObject
from app.shared.types.types_convert_utils import now_utc
from app.shared.utils.secret_redaction import redact_secret_text

_SERVER_OWNED_FRONTMATTER_FIELDS = frozenset(ServerOwnedFrontmatterField)


def reject_redaction_placeholders(content: str) -> None:
    """Reject masked placeholders in canonical write payloads.

    Args:
        content: Candidate canonical Markdown.

    Raises:
        ObsidianValidationError: A placeholder would overwrite exact source data.
    """
    for placeholder in RedactionPlaceholder:
        if placeholder.value in content:
            raise ObsidianValidationError(
                "REPAIR_CONTENT_PLACEHOLDER: canonical write payloads cannot "
                f"contain the redaction placeholder {placeholder.value}"
            )


class ObsidianNoteRepair:
    """Own raw and frontmatter note repair behind the existing mutation lane."""

    def __init__(
        self,
        repository: IObsidianIndexWriteRepository,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        record_index_error: Callable[[ObsidianIndexError], Awaitable[None]],
        skill_publication_policy: SkillPublicationPolicy | None,
    ) -> None:
        """Bind the repair operations to the shared source and write lane.

        Args:
            repository: PostgreSQL index used to commit parsed source.
            vault_config_store: Authoritative runtime Vault location.
            index_maintenance_coordinator: Existing source mutation lock owner.
            record_index_error: Best-effort owner for reindex diagnostics.
            skill_publication_policy: Loaded policy for Active Skill repair.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._record_index_error = record_index_error
        self._skill_publication_policy = skill_publication_policy

    async def repair_note_raw(
        self,
        *,
        path: str,
        expected_content_hash: str,
        raw_content: str,
    ) -> ObsidianNote:
        """Replace one note's raw source after CAS and parse validation.

        This is the bounded write side of the raw-repair workflow: the
        caller reads the raw source, fixes the frontmatter or body, and
        submits the full replacement text. The replacement is accepted
        only when the byte-hash CAS matches, the content is secret-free,
        and the repaired source parses cleanly — so a malformed note can
        be recovered in place without a quarantine detour.

        Args:
            path: Vault-relative Markdown path of the note to repair.
            expected_content_hash: Rust content hash of the current bytes.
            raw_content: Full replacement Markdown source.

        Returns:
            The repaired note as parsed and indexed after the write.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_raw_repair", wait=True
        ):
            safe_path = str(safe_relative_path(path))
            config = self._vault_config_store.current()
            absolute = resolve_note_path(
                vault_path=config.vault_path, relative_path=safe_path
            )
            if not absolute.exists():
                raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
            try:
                current_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, path=absolute, max_source_bytes=None),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except (OSError, UnicodeError) as exc:
                raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
            current_hash = hash_text(current_text)
            if current_hash != expected_content_hash:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: expected content hash does not match "
                    f"the current note: {safe_path}",
                    current_content_hash=current_hash,
                )
            reject_redaction_placeholders(raw_content)
            redaction = redact_secret_text(raw_content)
            if redaction.blocked:
                raise ObsidianValidationError(
                    "high-risk secret content cannot be saved"
                )
            if redaction.redaction_count > 0:
                # Masking a canonical write payload would persist placeholders in
                # place of the caller's exact bytes; repair must fail closed.
                raise ObsidianValidationError(
                    "REPAIR_CONTENT_REDACTED: replacement source contains "
                    "secret-like values; submit the exact source bytes instead"
                )
            content = raw_content
            if active_skill_path(safe_path):
                policy = (
                    self._skill_publication_policy
                    or default_skill_publication_policy(None)
                )
                content = await anyio.to_thread.run_sync(
                    partial(policy.validate_markdown, content, path=safe_path)
                )
            try:
                parse_markdown_document(content)
            except ValueError as exc:
                raise ObsidianValidationError(
                    f"REPAIR_CONTENT_INVALID: repaired source must parse: {exc}"
                ) from exc
            try:
                index_payload = await run_critical_sync(
                    partial(
                        source_persistence.persist_and_index,
                        absolute,
                        content,
                        safe_path,
                        config.alexandria_root,
                        expected_source_hash=expected_content_hash,
                    ),
                )
            except ValueError as exc:
                await run_critical_sync(
                    partial(
                        source_persistence.restore_source_if_owned,
                        absolute=absolute,
                        expected_document=content,
                        previous_document=current_text,
                    )
                )
                raise ObsidianValidationError(f"REPAIR_CONTENT_INVALID: {exc}") from exc
            if index_payload is None:
                await run_critical_sync(
                    partial(
                        source_persistence.restore_source_if_owned,
                        absolute=absolute,
                        expected_document=content,
                        previous_document=current_text,
                    )
                )
                raise ObsidianValidationError(
                    "repaired note is missing Alexandria frontmatter"
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

    async def repair_note_frontmatter(
        self,
        *,
        path: str,
        expected_content_hash: str,
        replacement_frontmatter: JSONObject,
    ) -> ObsidianFrontmatterRepairResult:
        """Replace one note's frontmatter while preserving exact body bytes.

        This is the byte-preserving repair for stale or malformed frontmatter:
        the durable body bytes are spliced in front of the replacement
        frontmatter block without re-serializing the body, server-owned fields
        are refused in caller input, and redaction placeholders are refused.

        Args:
            path: Vault-relative Markdown path of the note to repair.
            expected_content_hash: Rust content hash of the current bytes.
            replacement_frontmatter: Complete replacement frontmatter mapping.

        Returns:
            Before/after hash evidence with body preservation proof.

        Raises:
            ObsidianWriteConflictError: When the CAS hash does not match.
            ObsidianValidationError: When the repair cannot preserve the body
                or the replacement is not acceptable canonical frontmatter.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_frontmatter_repair", wait=True
        ):
            safe_path = str(safe_relative_path(path))
            config = self._vault_config_store.current()
            absolute = resolve_note_path(
                vault_path=config.vault_path, relative_path=safe_path
            )
            if not absolute.exists():
                raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
            try:
                current_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, path=absolute, max_source_bytes=None),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except (OSError, UnicodeError) as exc:
                raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
            content_hash_before = hash_text(current_text)
            if content_hash_before != expected_content_hash:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: expected content hash does not match "
                    f"the current note: {safe_path}",
                    current_content_hash=content_hash_before,
                )
            _, body_before = split_frontmatter_region(current_text)
            body_hash_before = hash_text(body_before)
            forbidden = sorted(
                field
                for field in replacement_frontmatter
                if field in _SERVER_OWNED_FRONTMATTER_FIELDS
            )
            if forbidden:
                raise ObsidianValidationError(
                    "REPAIR_FRONTMATTER_SERVER_OWNED: forbidden fields: "
                    + ", ".join(forbidden)
                )
            try:
                previous_frontmatter = parse_markdown_document(current_text).frontmatter
            except ValueError:
                removed = []
            else:
                removed = sorted(
                    set(previous_frontmatter) & _SERVER_OWNED_FRONTMATTER_FIELDS
                )
            caller_frontmatter = replacement_frontmatter
            rendered_block = render_frontmatter_block(caller_frontmatter)
            reject_redaction_placeholders(rendered_block)
            redaction = redact_secret_text(rendered_block)
            if redaction.blocked or redaction.redaction_count > 0:
                raise ObsidianValidationError(
                    "REPAIR_FRONTMATTER_REDACTED: replacement frontmatter contains "
                    "secret-like values; repair must fail closed"
                )
            repaired_text = rendered_block + body_before
            if active_skill_path(safe_path):
                policy = (
                    self._skill_publication_policy
                    or default_skill_publication_policy(None)
                )
                repaired_text = await anyio.to_thread.run_sync(
                    partial(policy.validate_markdown, repaired_text, path=safe_path)
                )
            try:
                index_payload = await run_critical_sync(
                    partial(
                        source_persistence.persist_and_index,
                        absolute,
                        repaired_text,
                        safe_path,
                        config.alexandria_root,
                        expected_source_hash=expected_content_hash,
                    ),
                )
            except ValueError as exc:
                await run_critical_sync(
                    partial(
                        source_persistence.restore_source_if_owned,
                        absolute=absolute,
                        expected_document=repaired_text,
                        previous_document=current_text,
                    )
                )
                raise ObsidianValidationError(
                    f"REPAIR_FRONTMATTER_INVALID: repaired source must parse: {exc}"
                ) from exc
            if index_payload is None:
                await run_critical_sync(
                    partial(
                        source_persistence.restore_source_if_owned,
                        absolute=absolute,
                        expected_document=repaired_text,
                        previous_document=current_text,
                    )
                )
                raise ObsidianValidationError(
                    "repaired note is missing Alexandria frontmatter"
                )
            try:
                verified_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, path=absolute, max_source_bytes=None),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except (OSError, UnicodeError) as exc:
                raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
            _block_after, body_after = split_frontmatter_region(verified_text)
            body_exact = body_after == body_before
            try:
                note = await self._repository.upsert_note(index_payload)
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
            return ObsidianFrontmatterRepairResult(
                content_hash_before=content_hash_before,
                content_hash_after=hash_text(verified_text),
                body_hash_before=body_hash_before,
                body_hash_after=hash_text(body_after),
                body_byte_exact_preserved=body_exact,
                removed_server_owned_fields=tuple(removed),
                parse_status="OK",
                index_status=note.index_status.value,
                note_id=note.note_id,
                relative_path=note.relative_path,
            )
