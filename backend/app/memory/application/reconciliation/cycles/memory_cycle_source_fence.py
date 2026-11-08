"""Canonical source revision fencing for aggregate Memory cycles."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_cycle import MemoryCycleSourceSnapshot
from app.memory.domain.entities.memory_existing_reconciliation import (
    ExistingMemoryPlanPreview,
)
from app.memory.domain.entities.memory_reconciliation import MemoryRecallCandidate
from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_cycle_exceptions import (
    MemoryCycleRecoveryRequiredError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue


class MemoryCycleContextSourcePort(Protocol):
    """Existing Context read authority for non-Obsidian source identities."""

    async def get(self, context_id: str) -> ContextRecord:
        """Read one current Context through its owning source repository.

        Args:
            context_id: Identifier of the Context record to read.

        Returns:
            Current ContextRecord from the owning repository.
        """


class MemoryCycleSourceFence:
    """Verify indexed Context candidates against canonical source revisions."""

    def __init__(
        self,
        source: ObsidianReadPort,
        context_reader: MemoryCycleContextSourcePort,
    ) -> None:
        """Initialize existing Obsidian and Context source authorities.

        Args:
            source: Canonical Obsidian note reader.
            context_reader: SQL-backed Context reader.
        """
        self._source = source
        self._context_reader = context_reader

    async def snapshot(
        self,
        previews: tuple[ExistingMemoryPlanPreview, ...],
    ) -> tuple[MemoryCycleSourceSnapshot, ...]:
        """Read every selected and compared source exactly once per identity.

        Args:
            previews: Existing memory plan previews containing source identities.

        Returns:
            Sorted tuple of verified source revision snapshots.
        """
        requests = _source_requests(previews)
        snapshots: list[MemoryCycleSourceSnapshot] = []
        for context_id, canonical_path, content_hash in requests:
            snapshots.append(
                await self._read_one(
                    context_id=context_id,
                    canonical_path=canonical_path,
                    expected_content_hash=content_hash,
                )
            )
        return tuple(sorted(snapshots, key=lambda item: item.context_id))

    async def refresh(
        self,
        snapshot: tuple[MemoryCycleSourceSnapshot, ...],
        extra_context_ids: tuple[str, ...] = (),
    ) -> tuple[MemoryCycleSourceSnapshot, ...]:
        """Capture post-mutation revisions for checkpoint replay.

        Intentional child mutations may change a canonical note revision. This
        refresh reads the admitted identities after commit instead of comparing
        them with their pre-apply revision forever.

        Args:
            snapshot: Pre-mutation source revision snapshots.
            extra_context_ids: Additional context identifiers created or touched.

        Returns:
            Sorted tuple of post-mutation source revision snapshots.

        Raises:
            MemoryCycleRecoveryRequiredError: If a canonical note cannot be read
                or its projection is stale after mutation.
        """
        known = {item.context_id: item for item in snapshot}
        for context_id in extra_context_ids:
            known.setdefault(
                context_id,
                MemoryCycleSourceSnapshot(
                    context_id=context_id,
                    canonical_path="",
                    content_hash="",
                    source_revision="",
                ),
            )
        refreshed: list[MemoryCycleSourceSnapshot] = []
        for item in known.values():
            if not item.context_id.startswith("obsidian:"):
                refreshed.append(
                    await self._read_context(
                        context_id=item.context_id,
                        canonical_path=item.canonical_path,
                        expected_content_hash=item.content_hash,
                    )
                )
                continue
            note_id = item.context_id.removeprefix("obsidian:").strip()
            try:
                note = await self._source.read_note(note_id)
            except Exception as exc:
                raise MemoryCycleRecoveryRequiredError(
                    "MEMORY_CYCLE_SOURCE_UNAVAILABLE: post-mutation source readback "
                    "could not verify the canonical note"
                ) from exc
            if note.index_status is not ObsidianIndexStatus.INDEXED:
                raise MemoryCycleRecoveryRequiredError(
                    "MEMORY_CYCLE_SOURCE_INDEX_STALE: post-mutation projection "
                    "is not current"
                )
            refreshed.append(
                MemoryCycleSourceSnapshot(
                    context_id=item.context_id,
                    canonical_path=note.relative_path,
                    content_hash=note.content_hash,
                    source_revision=_obsidian_revision(note),
                )
            )
        return tuple(sorted(refreshed, key=lambda value: value.context_id))

    async def _read_one(
        self,
        *,
        context_id: str,
        canonical_path: str,
        expected_content_hash: str,
    ) -> MemoryCycleSourceSnapshot:
        """Read one source and fail closed on stale index or content mismatch.

        Args:
            context_id: Canonical context or obsidian-prefixed note identifier.
            canonical_path: Expected canonical path from the index candidate.
            expected_content_hash: Expected content hash from the index candidate.

        Returns:
            Verified source revision snapshot.

        Raises:
            MemoryCycleRecoveryRequiredError: If the source is unreadable, not
                indexed, or differs in path or content hash.
        """
        if not context_id.startswith("obsidian:"):
            return await self._read_context(
                context_id=context_id,
                canonical_path=canonical_path,
                expected_content_hash=expected_content_hash,
            )
        note_id = context_id.removeprefix("obsidian:").strip()
        if not note_id:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_ID_INVALID: canonical source id is empty"
            )
        try:
            note = await self._source.read_note(note_id)
        except Exception as exc:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_UNAVAILABLE: canonical Markdown could not be "
                "read while preserving the durable source"
            ) from exc
        if note.index_status is not ObsidianIndexStatus.INDEXED:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_INDEX_STALE: canonical Markdown is readable "
                "but the indexed projection is not current"
            )
        if note.relative_path != canonical_path:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_PATH_CHANGED: canonical source path changed"
            )
        if note.content_hash != expected_content_hash:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_CONTENT_CHANGED: canonical source body "
                "differs from the indexed candidate"
            )
        return MemoryCycleSourceSnapshot(
            context_id=context_id,
            canonical_path=note.relative_path,
            content_hash=note.content_hash,
            source_revision=_obsidian_revision(note),
        )

    async def _read_context(
        self,
        *,
        context_id: str,
        canonical_path: str,
        expected_content_hash: str,
    ) -> MemoryCycleSourceSnapshot:
        """Read and fence one SQL-owned Context through ContextService.get.

        Args:
            context_id: Identifier of the SQL-owned Context record.
            canonical_path: Expected canonical path when previously recorded.
            expected_content_hash: Expected content hash when previously recorded.

        Returns:
            Verified source revision snapshot for the SQL-owned Context.

        Raises:
            MemoryCycleRecoveryRequiredError: If the Context cannot be read or
                its path or content hash changed.
        """
        try:
            context = await self._context_reader.get(context_id)
        except Exception as exc:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_UNAVAILABLE: Context source could not be "
                "read while preserving durable state"
            ) from exc
        fresh_path = _context_path(context)
        fresh_hash = context_content_hash(context)
        if canonical_path and fresh_path != canonical_path:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_PATH_CHANGED: Context source path changed"
            )
        if expected_content_hash and fresh_hash != expected_content_hash:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_SOURCE_CONTENT_CHANGED: Context source revision "
                "differs from the indexed candidate"
            )
        return MemoryCycleSourceSnapshot(
            context_id=context_id,
            canonical_path=fresh_path,
            content_hash=fresh_hash,
            source_revision=_context_revision(context),
        )


def _source_requests(
    previews: tuple[ExistingMemoryPlanPreview, ...],
) -> tuple[tuple[str, str, str], ...]:
    """Collect selected and compared source identities deterministically.

    Args:
        previews: Plan previews containing selected and compared contexts.

    Returns:
        Sorted tuple of (context_id, canonical_path, content_hash) triples.
    """
    requests: dict[str, tuple[str, str]] = {}
    for preview in previews:
        requests[preview.context.id] = (
            _context_path(preview.context),
            preview.content_hash,
        )
        for candidate in preview.compared_contexts:
            requests[candidate.context_id] = (
                _candidate_path(candidate),
                candidate.content_hash,
            )
    return tuple(
        (context_id, path, content_hash)
        for context_id, (path, content_hash) in sorted(requests.items())
    )


def _context_path(context: ContextRecord) -> str:
    """Extract a selected Context canonical path without dynamic access.

    Args:
        context: Context record to inspect.

    Returns:
        Vault-relative path if present in metadata, otherwise context:<id>.
    """
    value: JSONValue | None = context.context_metadata.get("relative_path")
    return (
        value.strip()
        if isinstance(value, str) and value.strip()
        else f"context:{context.id}"
    )


def _candidate_path(candidate: MemoryRecallCandidate) -> str:
    """Extract a compared candidate canonical path from its source refs.

    Args:
        candidate: Recall candidate to inspect.

    Returns:
        First non-empty source reference detail path, or context:<id>.
    """
    for source_ref in candidate.source_refs:
        if source_ref.detail_path.strip():
            return source_ref.detail_path
    return f"context:{candidate.context_id}"


def context_content_hash(context: ContextRecord) -> str:
    """Return the canonical Context body hash from metadata or body.

    Args:
        context: Context record to hash.

    Returns:
        Recorded metadata content_hash if present, otherwise hashed body text.
    """
    value: JSONValue | None = context.context_metadata.get("content_hash")
    return (
        value
        if isinstance(value, str) and value.strip()
        else hash_text(context.content)
    )


def _context_revision(context: ContextRecord) -> str:
    """Hash full SQL-owned metadata and body for replay fencing.

    Args:
        context: Context record to fingerprint.

    Returns:
        SHA-256 hex digest of the canonical Context payload.
    """
    payload: JSONObject = {
        "context_id": context.id,
        "canonical_path": _context_path(context),
        "content_hash": context_content_hash(context),
        "content": context.content,
        "metadata": dict(context.context_metadata),
    }
    return sha256(dumps_canonical_json(payload)).hexdigest()


def _obsidian_revision(note: ObsidianNote) -> str:
    """Hash source identity, body hash, and complete canonical frontmatter.

    Args:
        note: Obsidian note to fingerprint.

    Returns:
        SHA-256 hex digest of the canonical note identity and frontmatter.
    """
    payload: JSONObject = {
        "note_id": note.note_id,
        "relative_path": note.relative_path,
        "content_hash": note.content_hash,
        "frontmatter": note.frontmatter,
    }
    return sha256(dumps_canonical_json(payload)).hexdigest()
