"""Admit and record durable ordinary note-write effects."""

from dataclasses import replace
from functools import partial
from pathlib import Path

import anyio
import anyio.to_thread

from app.obsidian.application.notes.mutations.mutation_evidence_enums import (
    MutationEvidenceCode,
)
from app.obsidian.application.notes.mutations.receipt_identity import (
    ReceiptIdentityPolicy,
)
from app.obsidian.application.notes.mutations.receipt_reader import (
    NOTE_MUTATION_RECEIPT_ADAPTER,
    NoteMutationReceiptReader,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    NoteMutationReceipt,
    ObsidianMutationOutcome,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianIdempotencyConflictError,
    ObsidianValidationError,
)
from app.shared.infrastructure.critical_task import run_critical_sync


def receipt_outcome(
    receipt: NoteMutationReceipt,
    *,
    replayed: bool = False,
    evidence: tuple[str, ...] = (),
) -> ObsidianMutationOutcome:
    """Project admission evidence into the common public outcome contract.

    Args:
        receipt: Current persisted note receipt.
        replayed: Whether the writer returned a readback instead of writing.
        evidence: Exact readback evidence codes.

    Returns:
        Immutable common mutation verdict.
    """
    return ObsidianMutationOutcome(
        operation="note_write",
        idempotency_key=receipt.idempotency_key,
        status=receipt.status,
        checkpoint_state="write_started" if receipt.effect_started else "admitted",
        canonical_path=receipt.canonical_path,
        note_id=receipt.note_id,
        content_hash=receipt.content_hash,
        version=receipt.version,
        mutation_id=receipt.mutation_id,
        operation_identity=receipt.operation_identity,
        committed_at=receipt.committed_at,
        error_summary=receipt.error_summary,
        replayed=replayed,
        evidence=evidence,
    )


class NoteMutationReceipts:
    """Record the existing durable evidence for ordinary note writes."""

    def __init__(self, vault_config_store: ObsidianVaultConfigStore) -> None:
        """Initialize the existing checkpoint location.

        Args:
            vault_config_store: Canonical Vault location owner.
        """
        self._vault_config_store = vault_config_store
        self._reader = NoteMutationReceiptReader(vault_config_store)

    async def admit(self, key: str, identity: str) -> NoteMutationReceipt:
        """Persist admission before resolving or mutating any source.

        Args:
            key: Original idempotency identity.
            identity: Canonical request fingerprint.

        Returns:
            Existing exact admission, or a newly durable pre-effect record.

        Raises:
            ObsidianIdempotencyConflictError: When the key names another request.
        """
        existing = await self._reader.load(key)
        if existing is not None:
            if existing.operation_identity != identity:
                raise ObsidianIdempotencyConflictError
            return existing
        receipt = NoteMutationReceipt(
            idempotency_key=key,
            mutation_id=ReceiptIdentityPolicy.mutation_id(key),
            operation_identity=identity,
            status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
        )
        await self.save(receipt)
        return receipt

    async def started(
        self,
        receipt: NoteMutationReceipt,
        *,
        path: str,
        note_id: str,
        document: str,
        absolute: Path,
    ) -> None:
        """Fence the exact intended bytes immediately before source replacement.

        Args:
            receipt: Admitted request identity.
            path: Exact canonical source path.
            note_id: Resolved source identity.
            document: Intended UTF-8 document bytes.
            absolute: Resolved filesystem effect target.
        """
        previous = await anyio.to_thread.run_sync(_source_hash, absolute)
        await self.save(
            replace(
                receipt,
                effect_started=True,
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                canonical_path=path,
                note_id=note_id,
                expected_source_hash=hash_text(document),
                previous_source_hash=previous,
            )
        )

    async def completed(
        self, receipt: NoteMutationReceipt, note: ObsidianNote
    ) -> ObsidianMutationOutcome:
        """Record observed source completion without claiming projection durability.

        Args:
            receipt: Admitted write identity.
            note: Observed canonical source result.

        Returns:
            Common committed receipt for this primary source effect.
        """
        current = await self._reader.load(receipt.idempotency_key) or receipt
        absolute = self._vault_config_store.current().vault_path / note.relative_path
        source_hash = await anyio.to_thread.run_sync(_source_hash, absolute)
        if source_hash is None:
            raise ObsidianValidationError("MUTATION_SOURCE_READBACK_REQUIRED")
        if current.effect_started and source_hash != current.expected_source_hash:
            raise ObsidianValidationError("MUTATION_SOURCE_DRIFTED_BEFORE_RECEIPT")
        version = note.frontmatter.get("version")
        completed = replace(
            receipt,
            status=ObsidianMutationOutcomeStatus.COMMITTED,
            effect_started=True,
            canonical_path=note.relative_path,
            note_id=note.note_id,
            expected_source_hash=source_hash,
            content_hash=note.content_hash,
            version=version
            if isinstance(version, int) and not isinstance(version, bool)
            else None,
            committed_at=note.modified_at,
            error_summary=None,
        )
        await self.save(completed)
        return receipt_outcome(
            completed,
            evidence=(
                MutationEvidenceCode.PRIMARY_SOURCE_COMMITTED.value,
                MutationEvidenceCode.PROJECTION_STATUS_IS_SEPARATE.value,
            ),
        )

    async def observe(
        self, receipt: NoteMutationReceipt, note: ObsidianNote | None
    ) -> ObsidianMutationOutcome:
        """Reconcile a started effect against exact bytes without writing a receipt.

        Args:
            receipt: Existing durable intent.
            note: Exact canonical readback; None when the target is absent.

        Returns:
            Primary-effect verdict, retaining uncertainty on absent/changed sources.
        """
        if not receipt.effect_started:
            return receipt_outcome(
                receipt, evidence=(MutationEvidenceCode.EFFECT_NOT_STARTED.value,)
            )
        if note is None:
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.UNKNOWN),
                evidence=(MutationEvidenceCode.STARTED_SOURCE_ABSENT.value,),
            )
        source_hash = await anyio.to_thread.run_sync(
            _source_hash,
            self._vault_config_store.current().vault_path / note.relative_path,
        )
        if note.note_id != receipt.note_id:
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.CONFLICTED),
                evidence=(MutationEvidenceCode.SOURCE_IDENTITY_CHANGED.value,),
            )
        if source_hash == receipt.expected_source_hash:
            version = note.frontmatter.get("version")
            return receipt_outcome(
                replace(
                    receipt,
                    status=ObsidianMutationOutcomeStatus.COMMITTED,
                    content_hash=note.content_hash,
                    committed_at=receipt.committed_at or note.modified_at,
                    version=version
                    if isinstance(version, int) and not isinstance(version, bool)
                    else None,
                ),
                evidence=(
                    MutationEvidenceCode.EXACT_SOURCE_MATCHES_INTENT.value,
                    MutationEvidenceCode.PROJECTION_STATUS_IS_SEPARATE.value,
                ),
            )
        if (
            receipt.status is not ObsidianMutationOutcomeStatus.COMMITTED
            and source_hash == receipt.previous_source_hash
            and source_hash is not None
        ):
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.NOT_COMMITTED),
                evidence=(MutationEvidenceCode.EXACT_SOURCE_UNCHANGED.value,),
            )
        return receipt_outcome(
            replace(receipt, status=ObsidianMutationOutcomeStatus.CONFLICTED),
            evidence=(MutationEvidenceCode.SOURCE_CHANGED_SINCE_ADMISSION.value,),
        )

    async def failed(
        self, receipt: NoteMutationReceipt, error: Exception, *, conflicted: bool
    ) -> None:
        """Preserve unknown effects; never infer no commit from a transport error.

        Args:
            receipt: Original admitted write identity.
            error: Observed pipeline failure category.
            conflicted: Whether the failure definitively preceded effect admission.
        """
        current = await self._reader.load(receipt.idempotency_key) or receipt
        status = (
            ObsidianMutationOutcomeStatus.UNKNOWN
            if current.effect_started
            else ObsidianMutationOutcomeStatus.CONFLICTED
            if conflicted
            else ObsidianMutationOutcomeStatus.NOT_COMMITTED
        )
        await self.save(
            replace(current, status=status, error_summary=type(error).__name__)
        )

    async def save(self, receipt: NoteMutationReceipt) -> None:
        """Persist typed evidence using the existing fsync checkpoint primitive.

        Args:
            receipt: Owned immutable mutation state to record.
        """
        ReceiptIdentityPolicy.validate_receipt(receipt)
        await run_critical_sync(
            partial(
                ObsidianReportBundleRunStore(
                    vault_path=self._vault_config_store.current().vault_path
                ).save_typed,
                receipt.mutation_id,
                receipt,
                NOTE_MUTATION_RECEIPT_ADAPTER,
            )
        )


def _source_hash(path: Path) -> str | None:
    try:
        return hash_text(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return None
