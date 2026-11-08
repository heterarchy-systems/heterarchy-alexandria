"""Persist verified-upsert replay fences through the existing run store."""

from __future__ import annotations

from functools import partial
from typing import Final

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.application.notes.verified_upsert.mapping import EvidenceMapper
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedUpsertCheckpoint,
    ObsidianVerifiedUpsertRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.infrastructure.critical_task import run_critical_sync

_CHECKPOINT_ADAPTER: Final[TypeAdapter[ObsidianVerifiedUpsertCheckpoint]] = TypeAdapter(
    ObsidianVerifiedUpsertCheckpoint
)
_CHECKPOINT_PREFIX: Final[str] = "verified-upsert:"


class VerifiedUpsertCheckpoints:
    """Own store selection and typed checkpoint persistence for one invocation."""

    def __init__(
        self,
        vault_config_store: ObsidianVaultConfigStore,
        mapper: EvidenceMapper,
    ) -> None:
        """Bind the existing Vault configuration and shared evidence mapper."""
        self._vault_config_store = vault_config_store
        self._mapper = mapper

    def open_store(self) -> ObsidianReportBundleRunStore:
        """Open the existing report-bundle run store for the active Vault."""
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )

    async def load(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
    ) -> ObsidianVerifiedUpsertCheckpoint | None:
        """Load the typed checkpoint through the bounded blocking-I/O lane."""
        return await anyio.to_thread.run_sync(
            partial(
                store.load_typed,
                checkpoint_key,
                _CHECKPOINT_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def save(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
    ) -> None:
        """Save the typed checkpoint through the bounded blocking-I/O lane."""
        await run_critical_sync(
            partial(
                store.save_typed,
                checkpoint_key,
                checkpoint,
                _CHECKPOINT_ADAPTER,
            )
        )

    async def save_completed(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
        request: ObsidianVerifiedUpsertRequest,
        request_hash: str,
        note: ObsidianNote,
        warnings: tuple[str, ...],
    ) -> None:
        """Persist the completed source fence after verified readback."""
        checkpoint = ObsidianVerifiedUpsertCheckpoint(
            state=ObsidianVerifiedCheckpointState.COMPLETED,
            request_hash=request_hash,
            logical_identity=request.identity,
            canonical_path=note.relative_path,
            title=request.title,
            body_hash=hash_text(request.body),
            expected_content_hash=request.expected_content_hash,
            note_id=note.note_id,
            target_note_id=note.note_id,
            content_hash=note.content_hash,
            version=self._mapper.note_version(note),
            warnings=warnings,
        )
        await self.save(store, checkpoint_key, checkpoint)
