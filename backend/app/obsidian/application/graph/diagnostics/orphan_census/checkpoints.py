"""Typed persistence for bounded orphan census evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.domain.entities.obsidian_orphan_census import (
    ObsidianOrphanAcknowledgement,
    ObsidianOrphanCensusMetadata,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.infrastructure.critical_task import run_critical_sync

_ACK_PREFIX = "orphan-ack:"
_CENSUS_PREFIX = "orphan-census:"
_ACK_ADAPTER: TypeAdapter[ObsidianOrphanAcknowledgement] = TypeAdapter(
    ObsidianOrphanAcknowledgement
)
_CENSUS_ADAPTER: TypeAdapter[ObsidianOrphanCensusMetadata] = TypeAdapter(
    ObsidianOrphanCensusMetadata
)


class OrphanCensusCheckpointStore:
    """Own the existing typed run-store checkpoints for orphan diagnostics."""

    def __init__(self, vault_config_store: ObsidianVaultConfigStore) -> None:
        """Retain the canonical vault-location authority.

        Args:
            vault_config_store: Vault location authority for durable checkpoints.
        """
        self._vault_config_store = vault_config_store

    def _run_store(self) -> ObsidianReportBundleRunStore:
        """Return the vault-local acknowledgement store."""
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )

    async def observe_orphan(
        self,
        *,
        note_id: str,
        graph_run_id: str | None,
    ) -> ObsidianOrphanCensusMetadata:
        """Record first/last-seen census metadata under the census lease.

        Args:
            note_id: Stable identifier of the observed orphan note.
            graph_run_id: Graph projection run identifier in which the orphan was seen.

        Returns:
            Updated first/last-seen census metadata record.
        """
        now = utc_now()
        existing = await anyio.to_thread.run_sync(
            lambda: self._run_store().load_typed(
                _CENSUS_PREFIX + note_id,
                _CENSUS_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
        metadata = ObsidianOrphanCensusMetadata(
            note_id=note_id,
            first_seen_at=now if existing is None else existing.first_seen_at,
            last_seen_at=now,
            first_seen_run_id=(
                graph_run_id
                if existing is None
                else existing.first_seen_run_id or existing.graph_run_id
            ),
            last_seen_run_id=(
                graph_run_id
                if graph_run_id is not None
                else (
                    None
                    if existing is None
                    else existing.last_seen_run_id or existing.graph_run_id
                )
            ),
            graph_run_id=graph_run_id,
        )
        await run_critical_sync(
            lambda: self._run_store().save_typed(
                _CENSUS_PREFIX + note_id,
                metadata,
                _CENSUS_ADAPTER,
            )
        )
        return metadata

    async def load_census_metadata(
        self, note_id: str
    ) -> ObsidianOrphanCensusMetadata | None:
        """Load historical first/last-seen metadata without mutating it.

        Args:
            note_id: Stable identifier of the note to inspect.

        Returns:
            Persisted census metadata, or None when the note has not been observed.
        """
        metadata = await anyio.to_thread.run_sync(
            lambda: self._run_store().load_typed(
                _CENSUS_PREFIX + note_id,
                _CENSUS_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )
        if metadata is None:
            return None
        return replace(
            metadata,
            first_seen_run_id=metadata.first_seen_run_id or metadata.graph_run_id,
            last_seen_run_id=metadata.last_seen_run_id or metadata.graph_run_id,
        )

    async def load_acknowledgement(
        self, note_id: str
    ) -> ObsidianOrphanAcknowledgement | None:
        """Load one acknowledgement through the bounded blocking-I/O lane.

        Args:
            note_id: Stable identifier of the note to inspect.

        Returns:
            Persisted orphan acknowledgement, or None when unacknowledged.
        """
        return await anyio.to_thread.run_sync(
            lambda: self._run_store().load_typed(_ACK_PREFIX + note_id, _ACK_ADAPTER),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def save_acknowledgement(
        self, acknowledgement: ObsidianOrphanAcknowledgement
    ) -> None:
        """Persist one acknowledgement under its caller's critical lease.

        Args:
            acknowledgement: Validated orphan acknowledgement record to persist.
        """
        await run_critical_sync(
            lambda: self._run_store().save_typed(
                _ACK_PREFIX + acknowledgement.note_id,
                acknowledgement,
                _ACK_ADAPTER,
            )
        )


def utc_now() -> datetime:
    """Return the current aware UTC timestamp.

    Returns:
        Current timezone-aware UTC datetime.
    """
    return datetime.now(UTC)
