"""Read existing operation checkpoints and canonical note evidence."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedUpsertCheckpoint,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateCheckpoint
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianNotFoundError,
)

_VERIFIED_UPSERT_ADAPTER = TypeAdapter(ObsidianVerifiedUpsertCheckpoint)
_RELATE_ADAPTER = TypeAdapter(ObsidianRelateCheckpoint)


@dataclass(frozen=True, slots=True)
class OutcomeReadbackFailure:
    """Marker for a canonical readback that could not be completed."""

    error_type: str


class OutcomeEvidenceReader:
    """Read durable checkpoint and canonical note evidence through existing owners."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        vault_config_store: ObsidianVaultConfigStore,
    ) -> None:
        """Initialize the read-only outcome boundary."""
        self._obsidian_service = obsidian_service
        self._vault_config_store = vault_config_store

    async def load_verified_checkpoint(
        self,
        checkpoint_key: str,
    ) -> ObsidianVerifiedUpsertCheckpoint | None:
        """Load one verified-upsert checkpoint through the bounded I/O lane."""
        return await anyio.to_thread.run_sync(
            partial(
                self._run_store().load_typed,
                checkpoint_key,
                _VERIFIED_UPSERT_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def load_relate_checkpoint(
        self,
        checkpoint_key: str,
    ) -> ObsidianRelateCheckpoint | None:
        """Load one relate checkpoint through the bounded I/O lane."""
        return await anyio.to_thread.run_sync(
            partial(
                self._run_store().load_typed,
                checkpoint_key,
                _RELATE_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def read_path_if_present(
        self,
        path: str,
    ) -> ObsidianNote | OutcomeReadbackFailure | None:
        """Read one exact canonical path, distinguishing not-found from failure."""
        try:
            return await self._obsidian_service.read_note_by_path(path)
        except ObsidianNotFoundError:
            return None
        except (OSError, ObsidianDomainError) as exc:
            return OutcomeReadbackFailure(error_type=type(exc).__name__)

    def _run_store(self) -> ObsidianReportBundleRunStore:
        """Return the existing report-bundle checkpoint authority."""
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )
