"""Read canonical sources and classify verified-upsert observation evidence."""

from __future__ import annotations

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_index,
)
from app.obsidian.application.notes.verified_upsert.mapping import EvidenceMapper
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedUpsertSelector,
    ObsidianVerifiedUpsertVerification,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianCanonicalIdentityResult,
    ObsidianNote,
    ObsidianNoteWriteResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianNotFoundError,
    ObsidianValidationError,
)


class VerifiedUpsertReadback:
    """Own exact source reads and the public verification diagnosis."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        canonical_identity_service: ObsidianCanonicalIdentityService,
        mapper: EvidenceMapper,
    ) -> None:
        """Bind the canonical service boundaries and shared evidence mapper."""
        self._obsidian_service = obsidian_service
        self._canonical_identity_service = canonical_identity_service
        self._mapper = mapper

    async def verify(
        self,
        selector: ObsidianVerifiedUpsertSelector,
    ) -> ObsidianVerifiedUpsertVerification:
        """Diagnose source, identity, index, and duplicate evidence in one read."""
        if selector.identity is not None:
            resolution = (
                await self._canonical_identity_service.resolve_logical_identity(
                    selector.identity
                )
            )
            if resolution.existing_note_id is None:
                return ObsidianVerifiedUpsertVerification(
                    source_readable=False,
                    canonical_identity_resolved=False,
                    indexed=False,
                    vector_current=None,
                    graph_current=None,
                    duplicate_safe=(
                        False
                        if resolution.resolution == "AMBIGUOUS_CANONICAL_IDENTITY"
                        else None
                    ),
                    temporal_authority_consistent=None,
                    note_id=None,
                    canonical_path=resolution.canonical_path,
                    content_hash=None,
                    version=None,
                    warnings=("logical_identity_not_found",),
                )
            note = await self._obsidian_service.read_note(resolution.existing_note_id)
            duplicate_safe = len(resolution.candidate_paths) <= 1
            canonical_resolved = resolution.resolution == "EXISTING_CANONICAL_FAMILY"
        elif selector.note_id is not None:
            note = await self._obsidian_service.read_note(selector.note_id)
            duplicate_safe = True
            canonical_resolved = True
        else:
            path = selector.path
            if path is None:
                raise ObsidianValidationError("verified upsert selector is empty")
            note = await self._obsidian_service.read_note_by_path(path)
            duplicate_safe = True
            canonical_resolved = True
        return ObsidianVerifiedUpsertVerification(
            source_readable=True,
            canonical_identity_resolved=canonical_resolved,
            indexed=note.index_status is ObsidianIndexStatus.INDEXED,
            vector_current=None,
            graph_current=None,
            duplicate_safe=duplicate_safe,
            temporal_authority_consistent=None,
            note_id=note.note_id,
            canonical_path=note.relative_path,
            content_hash=note.content_hash,
            version=self._mapper.note_version(note),
        )

    async def read_path_if_present(self, path: str) -> ObsidianNote | None:
        """Read one exact canonical path, preserving the not-found distinction."""
        try:
            return await self._obsidian_service.read_note_by_path(path)
        except ObsidianNotFoundError:
            return None

    async def read_existing_for_resolution(
        self,
        resolution: ObsidianCanonicalIdentityResult,
    ) -> ObsidianNote | None:
        """Reuse the identity snapshot until a freshness fence is required.

        The canonical identity scan already parsed the source. Update paths defer
        the byte-level freshness check to the compare-and-swap write boundary,
        avoiding a redundant read. Replay paths verify the snapshot immediately
        before returning through ``verify_replay_candidate``.
        """
        payload = resolution.source_payload
        if payload is not None:
            return authoritative_note_from_index(payload)
        return await self.read_path_if_present(resolution.canonical_path)

    async def verify_replay_candidate(
        self,
        resolution: ObsidianCanonicalIdentityResult,
        existing: ObsidianNote,
    ) -> ObsidianNote | None:
        """Verify a snapshot-backed replay candidate before returning it unchanged."""
        payload = resolution.source_payload
        if payload is None:
            return existing
        verified = await self._obsidian_service.read_note_by_path_verified(
            relative_path=resolution.canonical_path,
            payload=payload,
        )
        if verified is not None:
            return verified
        return await self.read_path_if_present(resolution.canonical_path)

    async def verified_post_commit_readback(
        self,
        write_result: ObsidianNoteWriteResult,
    ) -> ObsidianNote | None:
        """Confirm the committed write by hash without a second parse.

        The write path already parsed the exact bytes it atomically persisted,
        so a matching re-read hash proves the disk state and the committed note
        is reused directly. Any mismatch falls back to the full parse readback.
        """
        source_hash = write_result.source_hash
        if source_hash:
            verified = await self._obsidian_service.read_note_from_write_evidence(
                relative_path=write_result.note.relative_path,
                source_hash=source_hash,
                expected_note=write_result.note,
            )
            if verified is not None:
                return verified
        return await self.read_path_if_present(write_result.note.relative_path)
