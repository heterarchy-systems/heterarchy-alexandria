"""Canonical Obsidian note search, read, and save service."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import partial
from pathlib import Path

import anyio
import anyio.to_thread
from sqlalchemy.exc import SQLAlchemyError

from app.obsidian.application.graph.diagnostics.obsidian_graph_link_renderer import (
    add_or_update_alexandria_links_section,
)
from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
)
from app.obsidian.application.notes.frontmatter.obsidian_frontmatter_redaction import (
    frontmatter_contains_secret_field,
    redacted_frontmatter,
)
from app.obsidian.application.notes.frontmatter.obsidian_note_write_metadata import (
    apply_write_history,
    frontmatter_for_explicit_write,
    write_is_unchanged,
)
from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    _source_parse_error_code,
    authoritative_note_from_index,
    authoritative_note_from_path_async,
    source_matches_hash,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_save_policy import (
    apply_context_save_policy,
)
from app.obsidian.application.notes.obsidian_note_indexer import (
    _read_source_text,
    note_index_from_path,
)
from app.obsidian.application.notes.obsidian_note_templates import (
    default_note_path,
    frontmatter_for_save,
)
from app.obsidian.application.service.notes.obsidian_note_mutation_receipts import (
    NoteMutationReceipts,
    note_mutation_identity,
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
    ObsidianNoteIndex,
    ObsidianSaveNote,
    ObsidianSearchQuery,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import NoteMutationReceipt
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianFrontmatterRepairResult,
    ObsidianIndexError,
    ObsidianNote,
    ObsidianNoteRawRead,
    ObsidianNoteWriteResult,
    ObsidianReindexResult,
    ObsidianSearchHit,
    ObsidianVaultSourceSnapshot,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianIndexErrorCode,
    ObsidianIndexStatus,
    ObsidianWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
    render_frontmatter_block,
    render_markdown_document,
    split_frontmatter_region,
    update_frontmatter_scalars,
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
    skill_body_hash,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianIdentityConflictError,
    ObsidianIndexWriteError,
    ObsidianNotFoundError,
    ObsidianStoredProjectionError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.extra_types import JSONObject
from app.shared.types.types_convert_utils import now_utc
from app.shared.utils.secret_redaction import redact_secret_text

logger = logging.getLogger(__name__)
DEFAULT_SOURCE_SCAN_LIMIT = 4096
SOURCE_METADATA_LOOKUP_TIMEOUT_SECONDS = 1.0
_RAW_READ_CODED_MESSAGE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*:")
_SERVER_OWNED_FRONTMATTER_FIELDS = frozenset(
    {
        "content_hash",
        "initial_content_hash",
        "previous_content_hash",
        "version",
        "created_at",
        "updated_at",
        "last_modified_by",
    }
)
_REDACTION_PLACEHOLDERS = (
    "<REDACTED_LONG_VALUE>",
    "<REDACTED>",
    "[BLOCKED_SECRET_CONTENT]",
)


def _reject_redaction_placeholders(content: str) -> None:
    """Reject known redaction placeholders in canonical write payloads.

    Placeholders enter agent context through masked read responses; saving
    them back would round-trip masking into the durable source.

    Args:
        content: Candidate canonical write payload text.

    Raises:
        ObsidianValidationError: When a known placeholder is present.
    """
    for placeholder in _REDACTION_PLACEHOLDERS:
        if placeholder in content:
            raise ObsidianValidationError(
                "REPAIR_CONTENT_PLACEHOLDER: canonical write payloads cannot "
                f"contain the redaction placeholder {placeholder}"
            )


def _persist_and_index(
    absolute: Path,
    document: str,
    safe_path: str,
    alexandria_root: str,
    *,
    expected_source_hash: str | None = None,
) -> ObsidianNoteIndex | None:
    """Persist source and parse its native index payload in one worker."""
    if expected_source_hash is not None:
        current_hash = hash_text(_read_source_text(absolute, max_source_bytes=None))
        if current_hash != expected_source_hash:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: source changed before repair persistence",
                current_content_hash=current_hash,
            )
    atomic_write_markdown(absolute, document)
    return note_index_from_path(
        absolute,
        safe_path,
        alexandria_root=alexandria_root,
    )


def _bounded_raw_read_error_message(message: str, mapped_code: str) -> str:
    """Bound a raw-read parse error to the parser's own coded diagnostics.

    Args:
        message: Raw parser exception message.
        mapped_code: Secret-free typed code mapped for this failure.

    Returns:
        The coded parser message, or the mapped code alone when uncoded.
    """
    if _RAW_READ_CODED_MESSAGE_PATTERN.match(message):
        return message
    return mapped_code


class ObsidianNoteService:
    """Own canonical note access, Markdown persistence, and index write-through."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        reindex: Callable[[], Awaitable[ObsidianReindexResult]],
        mark_context_superseded: ObsidianNoteSupersedeHook,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        source_snapshot: Callable[[int], Awaitable[ObsidianVaultSourceSnapshot]],
        source_scan_limit: int,
        skill_publication_policy: SkillPublicationPolicy | None = None,
    ) -> None:
        """Create the canonical note service.

        Args:
            repository: Rebuildable PostgreSQL index repository.
            vault_config_store: Runtime vault location provider.
            reindex: Vault index refresh callback.
            mark_context_superseded: Context lifecycle reconciliation callback.
            index_maintenance_coordinator: Process-wide rebuildable-index write lane.
            source_snapshot: Source-owned bounded Markdown snapshot callback.
            source_scan_limit: Maximum source files to scan for ID fallback reads.
            skill_publication_policy: Active Skill admission, composed lazily if absent.
        """
        if source_scan_limit <= 0:
            raise ObsidianValidationError("source_scan_limit must be greater than zero")
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._mutation_receipts = NoteMutationReceipts(vault_config_store)
        self._reindex = reindex
        self._mark_context_superseded = mark_context_superseded
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._source_snapshot = source_snapshot
        self._source_scan_limit = source_scan_limit
        self._skill_publication_policy = skill_publication_policy
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
        indexed, metadata_unavailable = await self._best_effort_index_lookup(
            lambda: self._repository.get_by_id(note_id)
        )
        if indexed is None:
            return await self._read_note_from_source_snapshot(
                note_id=note_id,
                indexed=None,
                metadata_unavailable=metadata_unavailable,
            )
        try:
            return await authoritative_note_from_path_async(
                vault_path=config.vault_path,
                relative_path=indexed.relative_path,
                alexandria_root=config.alexandria_root,
                indexed=indexed,
                expected_note_id=note_id,
            )
        except ObsidianNotFoundError:
            return await self._read_note_from_source_snapshot(
                note_id=note_id,
                indexed=indexed,
                metadata_unavailable=False,
            )

    async def read_note_raw(
        self,
        *,
        path: str | None = None,
        note_id: str | None = None,
    ) -> ObsidianNoteRawRead:
        """Read one note's raw source even when its frontmatter fails to parse.

        This is the read-only operator surface for minimal repair: the raw
        text, its Rust content hash, and bounded parse diagnostics are
        returned without ever leaking secret-like frontmatter content.

        Args:
            path: Vault-relative Markdown path.
            note_id: Stable note id from frontmatter.

        Returns:
            Raw source read result with bounded, secret-free diagnostics.
        """
        if path is not None:
            safe_path = str(safe_relative_path(path))
        elif note_id is not None:
            indexed = await self._repository.get_by_id(note_id)
            if indexed is None:
                raise ObsidianNotFoundError(f"Obsidian note not found: {note_id}")
            safe_path = indexed.relative_path
        else:
            raise ObsidianValidationError("path or note_id is required")
        config = self._vault_config_store.current()
        absolute = resolve_note_path(config.vault_path, safe_path)
        if not absolute.exists():
            raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
        try:
            text = await anyio.to_thread.run_sync(
                partial(_read_source_text, absolute, max_source_bytes=None),
                limiter=anyio.to_thread.current_default_thread_limiter(),
            )
        except (OSError, UnicodeError) as exc:
            raise ObsidianValidationError("SOURCE_READ_FAILED") from exc
        indexed_row, _ = await self._best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        if frontmatter_contains_secret_field(text):
            return ObsidianNoteRawRead(
                relative_path=safe_path,
                raw_text="",
                content_hash=None,
                byte_exact=False,
                byte_length=len(text.encode("utf-8")),
                parse_status="FRONTMATTER_SECRET_DETECTED",
                parse_error=None,
                frontmatter=None,
                body=None,
                note_id=None if indexed_row is None else indexed_row.note_id,
                index_status=(
                    None if indexed_row is None else indexed_row.index_status.value
                ),
            )
        content_hash = hash_text(text)
        frontmatter: JSONObject | None = None
        body: str | None = None
        parse_error: str | None = None
        try:
            document = parse_markdown_document(text)
        except ValueError as exc:
            parse_status = _source_parse_error_code(exc)
            parse_error = _bounded_raw_read_error_message(str(exc), parse_status)
        else:
            parse_status = "OK"
            frontmatter = frontmatter_json(document.frontmatter)
            body = document.body
        return ObsidianNoteRawRead(
            relative_path=safe_path,
            raw_text=text,
            content_hash=content_hash,
            byte_exact=True,
            byte_length=len(text.encode("utf-8")),
            parse_status=parse_status,
            parse_error=parse_error,
            frontmatter=frontmatter,
            body=body,
            note_id=None if indexed_row is None else indexed_row.note_id,
            index_status=(
                None if indexed_row is None else indexed_row.index_status.value
            ),
        )

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
            absolute = resolve_note_path(config.vault_path, safe_path)
            if not absolute.exists():
                raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
            try:
                current_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, absolute, max_source_bytes=None),
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
            _reject_redaction_placeholders(raw_content)
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
                    self._skill_publication_policy or default_skill_publication_policy()
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
                index_payload = await anyio.to_thread.run_sync(
                    partial(
                        _persist_and_index,
                        absolute,
                        content,
                        safe_path,
                        config.alexandria_root,
                        expected_source_hash=expected_content_hash,
                    ),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except ValueError as exc:
                atomic_write_markdown(absolute, current_text)
                raise ObsidianValidationError(f"REPAIR_CONTENT_INVALID: {exc}") from exc
            if index_payload is None:
                atomic_write_markdown(absolute, current_text)
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
                await self._record_index_error_best_effort(index_error)
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
            absolute = resolve_note_path(config.vault_path, safe_path)
            if not absolute.exists():
                raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
            try:
                current_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, absolute, max_source_bytes=None),
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
            _reject_redaction_placeholders(rendered_block)
            redaction = redact_secret_text(rendered_block)
            if redaction.blocked or redaction.redaction_count > 0:
                raise ObsidianValidationError(
                    "REPAIR_FRONTMATTER_REDACTED: replacement frontmatter contains "
                    "secret-like values; repair must fail closed"
                )
            repaired_text = rendered_block + body_before
            if active_skill_path(safe_path):
                policy = (
                    self._skill_publication_policy or default_skill_publication_policy()
                )
                repaired_text = await anyio.to_thread.run_sync(
                    partial(policy.validate_markdown, repaired_text, path=safe_path)
                )
            try:
                index_payload = await anyio.to_thread.run_sync(
                    partial(
                        _persist_and_index,
                        absolute,
                        repaired_text,
                        safe_path,
                        config.alexandria_root,
                        expected_source_hash=expected_content_hash,
                    ),
                    limiter=anyio.to_thread.current_default_thread_limiter(),
                )
            except ValueError as exc:
                atomic_write_markdown(absolute, current_text)
                raise ObsidianValidationError(
                    f"REPAIR_FRONTMATTER_INVALID: repaired source must parse: {exc}"
                ) from exc
            if index_payload is None:
                atomic_write_markdown(absolute, current_text)
                raise ObsidianValidationError(
                    "repaired note is missing Alexandria frontmatter"
                )
            try:
                verified_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, absolute, max_source_bytes=None),
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
                await self._record_index_error_best_effort(index_error)
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
            absolute = resolve_note_path(config.vault_path, safe_path)
            if not absolute.exists():
                raise ObsidianNotFoundError(f"Obsidian note not found: {safe_path}")
            if expected_source_hash is not None:
                current_text = await anyio.to_thread.run_sync(
                    partial(_read_source_text, absolute, max_source_bytes=None)
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
                        candidate = dict(frontmatter)
                        candidate["content_hash"] = canonical_hash
                        project = candidate.get("project")
                        context_identity_from_frontmatter(
                            candidate,
                            project=project if isinstance(project, str) else None,
                            status=str(candidate.get("status", "active")),
                            generated_content_hash=canonical_hash,
                        )
                        repaired = update_frontmatter_scalars(
                            current_text, {"content_hash": canonical_hash}
                        )
                        # This is a server-owned scalar repair, not a caller raw
                        # roundtrip. Reuse the source-CAS persistence primitive;
                        # the existing body and every other field stay byte exact.
                        try:
                            repaired_index = await anyio.to_thread.run_sync(
                                partial(
                                    _persist_and_index,
                                    absolute,
                                    repaired,
                                    safe_path,
                                    config.alexandria_root,
                                    expected_source_hash=expected_source_hash,
                                )
                            )
                        except ValueError as exc:
                            await anyio.to_thread.run_sync(
                                atomic_write_markdown, absolute, current_text
                            )
                            raise ObsidianValidationError(
                                "NOTE_MANAGED_HASH_REPAIR_INVALID"
                            ) from exc
                        if repaired_index is None:
                            await anyio.to_thread.run_sync(
                                atomic_write_markdown, absolute, current_text
                            )
                            raise ObsidianValidationError(
                                "NOTE_MANAGED_HASH_REPAIR_INVALID"
                            )
                        return await self._repository.upsert_note(repaired_index)
            try:
                index_payload = await anyio.to_thread.run_sync(
                    partial(
                        note_index_from_path,
                        absolute,
                        safe_path,
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
                await self._record_index_error_best_effort(index_error)
                raise ObsidianValidationError(
                    "INDEX_WRITE_FAILED: canonical Markdown was preserved for reindex"
                ) from exc

    async def read_note_by_path(self, relative_path: str) -> ObsidianNote:
        """Read one managed note by vault-relative path.

        Args:
            relative_path: Vault-relative Markdown path.

        Returns:
            Authoritative note loaded from Markdown.
        """
        config = self._vault_config_store.current()
        safe_path = str(safe_relative_path(relative_path))
        indexed, metadata_unavailable = await self._best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        return await authoritative_note_from_path_async(
            vault_path=config.vault_path,
            relative_path=safe_path,
            alexandria_root=config.alexandria_root,
            indexed=indexed,
            index_error=(
                "INDEX_METADATA_UNAVAILABLE" if metadata_unavailable else None
            ),
        )

    async def read_note_by_path_verified(
        self,
        relative_path: str,
        payload: ObsidianNoteIndex,
    ) -> ObsidianNote | None:
        """Reuse one known parsed payload when the source bytes still match.

        The source is re-read and byte-verified against the payload's Rust
        content hash instead of being reinterpreted. ``None`` means the bytes
        drifted, the file vanished, or index metadata was unavailable; callers
        must fall back to the full parse path to preserve the drift fence.

        Args:
            relative_path: Vault-relative Markdown path.
            payload: Previously parsed index payload for the same source.

        Returns:
            Authoritative note rebuilt from the payload, or ``None`` on drift.
        """
        if not payload.source_hash:
            return None
        config = self._vault_config_store.current()
        safe_path = str(safe_relative_path(relative_path))
        if payload.relative_path != safe_path:
            return None
        source_matches = await anyio.to_thread.run_sync(
            partial(
                source_matches_hash,
                config.vault_path,
                safe_path,
                config.alexandria_root,
                payload.source_hash,
                max_source_bytes=payload.size_bytes,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
        if not source_matches:
            return None
        indexed, metadata_unavailable = await self._best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        if metadata_unavailable:
            return None
        return authoritative_note_from_index(payload, indexed=indexed)

    async def read_note_from_write_evidence(
        self,
        relative_path: str,
        *,
        source_hash: str,
        expected_note: ObsidianNote,
    ) -> ObsidianNote | None:
        """Confirm one written source by hash and reuse its committed index note.

        The just-written Markdown is re-read and byte-verified against
        ``source_hash``. Because the committed note was mapped from the
        deterministic parse of exactly those bytes, a matching hash proves the
        readback without a second parse. ``None`` means unverified; callers
        must fall back to the full parse readback.

        Args:
            relative_path: Vault-relative Markdown path of the written note.
            source_hash: Rust-computed hash of the written document text.
            expected_note: Note produced by indexing the written source bytes.

        Returns:
            The committed authoritative note, or ``None`` when unverified.
        """
        config = self._vault_config_store.current()
        safe_path = str(safe_relative_path(relative_path))
        source_matches = await anyio.to_thread.run_sync(
            partial(
                source_matches_hash,
                config.vault_path,
                safe_path,
                config.alexandria_root,
                source_hash,
                max_source_bytes=expected_note.size_bytes,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
        if not source_matches:
            return None
        indexed, metadata_unavailable = await self._best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        if (
            metadata_unavailable
            or indexed is None
            or indexed != expected_note
            or indexed.relative_path != safe_path
        ):
            return None
        return indexed

    async def _best_effort_index_lookup(
        self,
        lookup: Callable[[], Awaitable[ObsidianNote | None]],
    ) -> tuple[ObsidianNote | None, bool]:
        """Read projection metadata without making it a source-read prerequisite."""
        try:
            async with asyncio.timeout(SOURCE_METADATA_LOOKUP_TIMEOUT_SECONDS):
                return await lookup(), False
        except (SQLAlchemyError, OSError):
            logger.warning("Obsidian index metadata is unavailable during source read")
            return None, True

    async def _read_note_from_source_snapshot(
        self,
        *,
        note_id: str,
        indexed: ObsidianNote | None,
        metadata_unavailable: bool,
    ) -> ObsidianNote:
        """Resolve an exact id from one complete bounded source snapshot."""
        snapshot = await self._source_snapshot(self._source_scan_limit)
        if not snapshot.complete or snapshot.errors:
            raise ObsidianValidationError(
                "SOURCE_SCAN_INCOMPLETE: cannot prove requested note id is "
                "absent or unique"
            )
        matches = [payload for payload in snapshot.notes if payload.note_id == note_id]
        if len(matches) > 1:
            raise ObsidianValidationError(
                "AMBIGUOUS_SOURCE_NOTE_ID: multiple canonical Markdown notes "
                "match the requested id"
            )
        if not matches:
            raise ObsidianNotFoundError(f"Obsidian note not found: {note_id}")
        return authoritative_note_from_index(
            matches[0],
            indexed=indexed,
            index_error=(
                "INDEX_METADATA_UNAVAILABLE" if metadata_unavailable else None
            ),
            expected_note_id=note_id,
        )

    async def save_note(self, payload: ObsidianSaveNote) -> ObsidianNote:
        """Create or replace one Alexandria-managed Markdown note.

        Args:
            payload: Save request with body and metadata.

        Returns:
            Saved note loaded through the index.
        """
        async with self._index_maintenance_coordinator.operation(
            "obsidian_note_mutation", wait=True
        ):
            receipt, replay = await self._admit_note_mutation(payload)
            if replay is not None:
                return replay
            try:
                note, _, _ = await self._save_note_serialized(payload, receipt=receipt)
                note.mutation_receipt = await self._mutation_receipts.completed(
                    receipt, note
                )
                return note
            except Exception as exc:
                await self._mutation_receipts.failed(
                    receipt,
                    exc,
                    conflicted=isinstance(
                        exc, (ObsidianWriteConflictError, ObsidianIdentityConflictError)
                    ),
                )
                raise

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
            receipt, replay = await self._admit_note_mutation(command.note, command)
            if replay is not None:
                note, mutated, source_hash = replay, False, replay.source_hash
                expected_operation = ObsidianWriteOperation.UNCHANGED
            else:
                try:
                    (
                        payload,
                        existing,
                        expected_operation,
                    ) = await self._write_target_resolver.resolve(command)
                    note, mutated, source_hash = await self._save_note_serialized(
                        payload,
                        existing_note=existing,
                        frontmatter_mode=command.frontmatter_mode,
                        receipt=receipt,
                    )
                    note.mutation_receipt = await self._mutation_receipts.completed(
                        receipt, note
                    )
                except Exception as exc:
                    await self._mutation_receipts.failed(
                        receipt,
                        exc,
                        conflicted=isinstance(
                            exc,
                            (ObsidianWriteConflictError, ObsidianIdentityConflictError),
                        ),
                    )
                    raise
        operation = expected_operation if mutated else ObsidianWriteOperation.UNCHANGED
        return ObsidianNoteWriteResult(
            operation=operation,
            write_mode=command.write_mode,
            match_by=command.match_by,
            note=note,
            storage_status="stored" if mutated else "unchanged",
            metadata_status=note.index_status.value,
            fts_status="indexed"
            if note.index_status is ObsidianIndexStatus.INDEXED
            else "unknown",
            graph_edge_index_status="indexed"
            if note.index_status is ObsidianIndexStatus.INDEXED
            else "unknown",
            graph_projection_status="stale" if mutated else "unknown",
            reindex_required=mutated
            or (
                note.mutation_receipt is not None
                and note.mutation_receipt.error_summary is not None
            ),
            warnings=("mutation_pipeline_reconciliation_required",)
            if note.mutation_receipt is not None
            and note.mutation_receipt.error_summary is not None
            else (),
            source_hash=source_hash,
        )

    async def _admit_note_mutation(
        self,
        payload: ObsidianSaveNote,
        command: ObsidianWriteNote | None = None,
    ) -> tuple[NoteMutationReceipt, ObsidianNote | None]:
        """Read back existing effects before any target resolver or source mutation."""
        key, identity = note_mutation_identity(payload, command)
        receipt = await self._mutation_receipts.admit(key, identity)
        if not receipt.effect_started:
            return receipt, None
        try:
            note = await self.read_note_by_path(receipt.canonical_path or "")
        except ObsidianNotFoundError:
            note = None
        outcome = await self._mutation_receipts.observe(receipt, note)
        if (
            outcome.status is ObsidianMutationOutcomeStatus.COMMITTED
            and note is not None
        ):
            note.mutation_receipt = replace(outcome, replayed=True)
            return receipt, note
        if outcome.status is ObsidianMutationOutcomeStatus.NOT_COMMITTED:
            admitted = replace(
                receipt,
                effect_started=False,
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
            )
            await self._mutation_receipts.save(admitted)
            return admitted, None
        if outcome.status is ObsidianMutationOutcomeStatus.CONFLICTED:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: mutation source drifted; reconcile before retry"
            )
        raise ObsidianCheckpointRecoveryRequiredError(receipt.mutation_id)

    async def _save_note_serialized(
        self,
        payload: ObsidianSaveNote,
        existing_note: ObsidianNote | None = None,
        frontmatter_mode: ObsidianFrontmatterMode | None = None,
        receipt: NoteMutationReceipt | None = None,
    ) -> tuple[ObsidianNote, bool, str | None]:
        """Save one note while serializing canonical read-check-replace writes.

        Args:
            payload: Validated payload for this operation.
            existing_note: Existing note used by this operation.
            frontmatter_mode: Frontmatter mode used by this operation.
            receipt: Durable ordinary-write admission when this is an effect path.

        Returns:
            tuple[ObsidianNote, bool, str | None] with the committed note, the
            mutation flag, and the Rust-computed hash of the written document
            text (``None`` when no new bytes were written).
        """
        config = self._vault_config_store.current()
        title = payload.title.strip()
        if not title:
            raise ObsidianValidationError("title is required")
        redaction = redact_secret_text(payload.body)
        if redaction.blocked:
            raise ObsidianValidationError("high-risk secret content cannot be saved")
        declared_skill_metadata = dict(payload.frontmatter)
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
        await self._validate_expected_source_state(
            payload=payload,
            indexed_note=indexed_note,
            safe_path=safe_path,
            vault_path=config.vault_path,
            alexandria_root=config.alexandria_root,
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
            payload.alexandria_type is AlexandriaNoteType.SKILL
            and active_skill_path(safe_path)
            and payload.status.casefold() in {"active", "current"}
        ):
            publication = (
                self._skill_publication_policy or default_skill_publication_policy()
            )
            declared = dict(frontmatter)
            if "capability_fingerprint" not in declared_skill_metadata:
                declared.pop("capability_fingerprint", None)
            else:
                declared["capability_fingerprint"] = declared_skill_metadata[
                    "capability_fingerprint"
                ]
            verification = await anyio.to_thread.run_sync(
                partial(publication.validate, body, declared, path=safe_path)
            )
            verification["skill_source_hash"] = skill_body_hash(
                redaction.redacted_content
            )
            frontmatter.update(verification)
        if (
            frontmatter_mode is not None
            and existing_note is not None
            and write_is_unchanged(
                existing=existing_note,
                desired_frontmatter=frontmatter,
                desired_body=body,
            )
        ):
            return existing_note, False, None
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
                return policy.duplicate, False, None
            frontmatter = policy.frontmatter
            supersedes_context_id = policy.supersedes_context_id
        document = render_markdown_document(frontmatter, body)
        if receipt is not None:
            await self._mutation_receipts.started(
                receipt,
                path=safe_path,
                note_id=note_id,
                document=document,
                absolute=absolute,
            )
        index_payload = await anyio.to_thread.run_sync(
            partial(
                _persist_and_index,
                absolute,
                document,
                safe_path,
                config.alexandria_root,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
        if index_payload is None:
            raise ObsidianValidationError(
                "saved note is missing Alexandria frontmatter"
            )
        try:
            note = await self._repository.upsert_note(index_payload)
        except ObsidianIndexWriteError as exc:
            try:
                source_readback = await authoritative_note_from_path_async(
                    vault_path=config.vault_path,
                    relative_path=safe_path,
                    alexandria_root=config.alexandria_root,
                    expected_note_id=note_id,
                )
            except (
                OSError,
                ValueError,
                ObsidianNotFoundError,
                ObsidianValidationError,
            ):
                source_readback = None
            index_error = ObsidianIndexError(
                note_path=safe_path,
                context_id=note_id,
                error_code=ObsidianIndexErrorCode.INDEX_WRITE_FAILED,
                error_message=str(exc),
                detected_at=now_utc(),
            )
            await self._record_index_error_best_effort(index_error)
            if source_readback is not None:
                raise ObsidianStoredProjectionError(
                    note=source_readback,
                    failed_stage="metadata_index",
                ) from exc
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
                try:
                    source_readback = await authoritative_note_from_path_async(
                        vault_path=config.vault_path,
                        relative_path=safe_path,
                        alexandria_root=config.alexandria_root,
                        indexed=note,
                        expected_note_id=note.note_id,
                    )
                except (
                    OSError,
                    ValueError,
                    ObsidianNotFoundError,
                    ObsidianValidationError,
                ):
                    source_readback = None
                index_error = ObsidianIndexError(
                    note_path=safe_path,
                    context_id=note.note_id,
                    error_code=index_error_code(exc),
                    error_message=str(exc),
                    detected_at=now_utc(),
                )
                await self._record_index_error_best_effort(index_error)
                if source_readback is not None:
                    raise ObsidianStoredProjectionError(
                        note=source_readback,
                        failed_stage="context_supersession",
                    ) from exc
                raise ObsidianValidationError(
                    "INDEX_WRITE_FAILED: replacement Markdown was preserved for "
                    "reindex reconciliation"
                ) from exc
        return note, True, index_payload.source_hash

    async def _validate_expected_source_state(
        self,
        *,
        payload: ObsidianSaveNote,
        indexed_note: ObsidianNote | None,
        safe_path: str,
        vault_path: Path,
        alexandria_root: str,
    ) -> None:
        """Reject CAS writes when canonical Markdown drifted from its projection.

        The PostgreSQL row remains a rebuildable projection.  When callers send
        ``expected_content_hash`` we therefore re-read the canonical source and
        require it to agree with the indexed projection before replacing the
        file.  This uses the normal authoritative parser because CONTEXT notes
        intentionally expose a logical/body content hash that differs from the
        raw-source hash.  CAS writes run in the coordinator's exclusive lane,
        which closes the same-token race for cooperating Alexandria writers.
        Arbitrary external editors do not share that lease, so this is a
        pre-replace drift fence rather than a claim of universal filesystem CAS.
        """
        expected = payload.expected_content_hash
        if expected is None or indexed_note is None:
            return
        if indexed_note.source_hash is not None and source_matches_hash(
            vault_path,
            safe_path,
            alexandria_root,
            indexed_note.source_hash,
            max_source_bytes=indexed_note.size_bytes,
        ):
            return
        try:
            current = await authoritative_note_from_path_async(
                vault_path=vault_path,
                relative_path=safe_path,
                alexandria_root=alexandria_root,
                indexed=indexed_note,
                expected_note_id=indexed_note.note_id,
            )
        except (
            OSError,
            ValueError,
            ObsidianNotFoundError,
            ObsidianValidationError,
        ) as exc:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: canonical Markdown cannot be verified "
                f"before compare-and-swap: {safe_path}"
            ) from exc
        if current.index_status is ObsidianIndexStatus.STALE:
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: canonical Markdown changed since the "
                f"indexed compare-and-swap token was observed: {safe_path}"
            )

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

        Args:
            index_error: Index error used by this operation.
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
