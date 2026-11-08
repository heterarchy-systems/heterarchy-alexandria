"""Serialize canonical-note writes and validate source compare-and-swap fences."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial

import anyio
import anyio.to_thread

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
    authoritative_note_from_path_async,
)
from app.obsidian.application.notes.lifecycle.obsidian_context_save_policy import (
    apply_context_save_policy,
)
from app.obsidian.application.notes.mutations.receipts import (
    NoteMutationReceipts,
)
from app.obsidian.application.notes.obsidian_note_templates import (
    default_note_path,
    frontmatter_for_save,
)
from app.obsidian.application.notes.writing import (
    obsidian_note_persistence as source_persistence,
)
from app.obsidian.application.service.notes.obsidian_note_service_contracts import (
    ObsidianNoteSupersedeHook,
)
from app.obsidian.application.service.notes.obsidian_write_target_resolver import (
    ObsidianWriteTargetResolver,
)
from app.obsidian.application.vault.index_errors import (
    index_error_code,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import NoteMutationReceipt
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianFrontmatterMode,
    ObsidianIndexErrorCode,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
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
from app.operations.application.skill_contract.skill_publication_policy import (
    SkillPublicationPolicy,
    active_skill_path,
    default_skill_publication_policy,
    skill_body_hash,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIndexWriteError,
    ObsidianNotFoundError,
    ObsidianStoredProjectionError,
    ObsidianValidationError,
)
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import now_utc
from app.shared.utils.secret_redaction import redact_secret_text


@dataclass(frozen=True, slots=True)
class NoteWriteCommit:
    """Immutable internal result for one serialized source write."""

    note: ObsidianNote
    mutated: bool
    source_hash: str | None


class ObsidianNoteWriter:
    """Prepare, commit and reconcile one serialized canonical-note write."""

    def __init__(
        self,
        repository: IObsidianIndexRepository,
        vault_config_store: ObsidianVaultConfigStore,
        write_target_resolver: ObsidianWriteTargetResolver,
        mutation_receipts: NoteMutationReceipts,
        mark_context_superseded: ObsidianNoteSupersedeHook,
        skill_publication_policy: SkillPublicationPolicy | None,
        record_index_error: Callable[[ObsidianIndexError], Awaitable[None]],
    ) -> None:
        """Create a writer with the existing index and receipt owners.

        Args:
            repository: PostgreSQL index projection and write boundary.
            vault_config_store: Shared current vault configuration.
            write_target_resolver: Existing target identity/CAS resolver.
            mutation_receipts: Shared durable mutation receipt authority.
            mark_context_superseded: Existing Context lifecycle callback.
            skill_publication_policy: Active Skill validation policy, when configured.
            record_index_error: Best-effort projection diagnostic writer.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store
        self._write_target_resolver = write_target_resolver
        self._mutation_receipts = mutation_receipts
        self._mark_context_superseded = mark_context_superseded
        self._skill_publication_policy = skill_publication_policy
        self._record_index_error = record_index_error

    async def save_note_serialized(
        self,
        payload: ObsidianSaveNote,
        existing_note: ObsidianNote | None = None,
        frontmatter_mode: ObsidianFrontmatterMode | None = None,
        receipt: NoteMutationReceipt | None = None,
    ) -> NoteWriteCommit:
        """Save one note while serializing canonical read-check-replace writes.

        Args:
            payload: Validated payload for this operation.
            existing_note: Existing note used by this operation.
            frontmatter_mode: Frontmatter mode used by this operation.
            receipt: Durable ordinary-write admission when this is an effect path.

        Returns:
            Immutable committed note, mutation state and raw source hash.
            ``source_hash`` is ``None`` when no new bytes were written.
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
        absolute = resolve_note_path(
            vault_path=config.vault_path, relative_path=safe_path
        )
        indexed_note = await self._repository.get_by_path(safe_path)
        self._write_target_resolver._validate_expected_content_hash(
            payload=payload,
            indexed_note=indexed_note,
            safe_path=safe_path,
        )
        await source_persistence.validate_expected_source_state(
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
            body=redaction.redacted_content,
            frontmatter=frontmatter,
        )
        if (
            payload.alexandria_type is AlexandriaNoteType.SKILL
            and active_skill_path(safe_path)
            and payload.status.casefold() in {"active", "current"}
        ):
            publication = (
                self._skill_publication_policy or default_skill_publication_policy(None)
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
            return NoteWriteCommit(note=existing_note, mutated=False, source_hash=None)
        if frontmatter_mode is not None:
            frontmatter = apply_write_history(
                frontmatter,
                existing=existing_note,
                body=body,
            )
        supersedes_context_id: str | None = None
        if payload.alexandria_type is AlexandriaNoteType.CONTEXT:
            policy = await apply_context_save_policy(
                payload=payload,
                note_id=note_id,
                frontmatter=frontmatter,
                body=body,
                repository=self._repository,
            )
            if policy.duplicate is not None:
                return NoteWriteCommit(
                    note=policy.duplicate, mutated=False, source_hash=None
                )
            frontmatter = policy.frontmatter
            supersedes_context_id = policy.supersedes_context_id
        document = render_markdown_document(frontmatter=frontmatter, body=body)
        if receipt is not None:
            await self._mutation_receipts.started(
                receipt,
                path=safe_path,
                note_id=note_id,
                document=document,
                absolute=absolute,
            )
        index_payload = await run_critical_sync(
            partial(
                source_persistence.persist_and_index,
                absolute=absolute,
                document=document,
                safe_path=safe_path,
                alexandria_root=config.alexandria_root,
            ),
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
            await self._record_index_error(index_error)
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
                await self._record_index_error(index_error)
                if source_readback is not None:
                    raise ObsidianStoredProjectionError(
                        note=source_readback,
                        failed_stage="context_supersession",
                    ) from exc
                raise ObsidianValidationError(
                    "INDEX_WRITE_FAILED: replacement Markdown was preserved for "
                    "reindex reconciliation"
                ) from exc
        return NoteWriteCommit(
            note=note, mutated=True, source_hash=index_payload.source_hash
        )
