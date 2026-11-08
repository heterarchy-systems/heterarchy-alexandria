"""Read and validate note mutation receipts through the checkpoint store."""

from functools import partial

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.application.notes.mutations.receipt_identity import (
    ReceiptIdentityPolicy,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import NoteMutationReceipt
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError

NOTE_MUTATION_RECEIPT_ADAPTER = TypeAdapter(NoteMutationReceipt)


class NoteMutationReceiptReader:
    """Bind one note-write selector to durable receipt evidence."""

    def __init__(self, vault_config_store: ObsidianVaultConfigStore) -> None:
        """Retain the canonical Vault location owner without performing I/O.

        Args:
            vault_config_store: Canonical Vault location owner.
        """
        self._vault_config_store = vault_config_store

    async def load(self, key: str) -> NoteMutationReceipt | None:
        """Read the typed receipt without changing state.

        Args:
            key: Original idempotency identity.

        Returns:
            Current receipt, or None before admission.
        """
        if not key.strip():
            raise ObsidianValidationError("idempotency_key must not be blank")
        mutation_id = ReceiptIdentityPolicy.mutation_id(key)
        return await self._load_by_mutation_id(
            mutation_id,
            expected_key=key,
        )

    async def load_by_mutation_id(
        self,
        mutation_id: str,
    ) -> NoteMutationReceipt | None:
        """Read one receipt by its namespaced, retry-safe mutation identifier.

        The selector is deliberately narrower than the underlying run-store
        key.  A caller cannot turn an arbitrary checkpoint into a note-write
        outcome, and a valid file whose embedded identity disagrees with the
        selector is treated as recovery-required evidence.
        """
        if not ReceiptIdentityPolicy.is_mutation_id(mutation_id):
            raise ObsidianValidationError("mutation_id must be note-write:<sha256>")
        return await self._load_by_mutation_id(mutation_id)

    async def _load_by_mutation_id(
        self,
        mutation_id: str,
        *,
        expected_key: str | None = None,
    ) -> NoteMutationReceipt | None:
        """Load and semantically bind one existing typed receipt."""
        receipt = await anyio.to_thread.run_sync(
            partial(
                self._store().load_typed, mutation_id, NOTE_MUTATION_RECEIPT_ADAPTER
            )
        )
        if receipt is None:
            return None
        return ReceiptIdentityPolicy.validate_receipt(
            receipt,
            expected_key=expected_key,
            expected_mutation_id=mutation_id,
        )

    def _store(self) -> ObsidianReportBundleRunStore:
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )
