"""Authoritative Markdown note reading and projection lookup."""

from __future__ import annotations

from functools import partial

import anyio
import anyio.to_thread

from app.obsidian.application.notes.lifecycle.obsidian_authoritative_read import (
    authoritative_note_from_index,
    source_matches_hash,
)
from app.obsidian.application.notes.reading.obsidian_note_reader import (
    best_effort_index_lookup,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianNoteIndex,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNote,
)
from app.obsidian.domain.repositories.obsidian_index_query_repository import (
    IObsidianIndexQueryRepository,
)
from app.obsidian.infrastructure.markdown.paths import (
    safe_relative_path,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)


class ObsidianNoteReadback:
    """Reuse parsed index payloads only after verifying canonical source bytes."""

    def __init__(
        self,
        repository: IObsidianIndexQueryRepository,
        vault_config_store: ObsidianVaultConfigStore,
    ) -> None:
        """Create readback verification over the shared index and vault.

        Args:
            repository: Indexed note projection used to confirm committed evidence.
            vault_config_store: Current authoritative Vault location provider.
        """
        self._repository = repository
        self._vault_config_store = vault_config_store

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
        metadata = await best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        if metadata.unavailable:
            return None
        return authoritative_note_from_index(payload, indexed=metadata.note)

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
        metadata = await best_effort_index_lookup(
            lambda: self._repository.get_by_path(safe_path)
        )
        indexed = metadata.note
        if (
            metadata.unavailable
            or indexed is None
            or indexed != expected_note
            or indexed.relative_path != safe_path
        ):
            return None
        return indexed
