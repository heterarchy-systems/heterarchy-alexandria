"""Resolve note mutation outcomes from their durable source evidence."""

from __future__ import annotations

from dataclasses import replace

from app.obsidian.application.notes.mutations.mutation_evidence_enums import (
    MutationEvidenceCode,
)
from app.obsidian.application.notes.mutations.outcome_evidence import (
    OutcomeEvidenceReader,
    OutcomeReadbackFailure,
)
from app.obsidian.application.notes.mutations.outcome_policy import (
    MutationOutcomePolicy,
    _aware_timestamp,
    _checkpoint_identity as checkpoint_identity,
    _note_version,
)
from app.obsidian.application.notes.mutations.receipt_reader import (
    NoteMutationReceiptReader,
)
from app.obsidian.application.notes.mutations.receipts import (
    NoteMutationReceipts,
    receipt_outcome,
)
from app.obsidian.application.notes.relations.obsidian_relation_mutation_service import (
    relation_present,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    ObsidianMutationOutcome,
)
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianDomainError,
    ObsidianNotFoundError,
    ObsidianValidationError,
)

_VERIFIED_UPSERT_PREFIX = "verified-upsert:"
_RELATE_PREFIX = "relate:"


class ObsidianMutationOutcomeService:
    """Answer retry-safety questions from durable fence evidence."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        vault_config_store: ObsidianVaultConfigStore,
    ) -> None:
        """Initialize the read-only outcome boundary."""
        self._obsidian_service = obsidian_service
        self._vault_config_store = vault_config_store
        self._evidence_reader = OutcomeEvidenceReader(
            obsidian_service=obsidian_service,
            vault_config_store=vault_config_store,
        )

    async def note_write_outcome(
        self,
        idempotency_key: str | None = None,
        *,
        mutation_id: str | None = None,
    ) -> ObsidianMutationOutcome:
        """Read generic create/update/batch evidence before a mutation retry.

        Args:
            idempotency_key: Original caller or request-derived stable identity.
            mutation_id: Direct namespaced receipt selector.

        Returns:
            Exact source evidence, with uncertainty preserved on readback failure.
        """
        if (idempotency_key is None) == (mutation_id is None):
            raise ObsidianValidationError(
                "exactly one of idempotency_key or mutation_id is required"
            )
        receipts = NoteMutationReceipts(self._vault_config_store)
        receipt_reader = NoteMutationReceiptReader(self._vault_config_store)
        try:
            receipt = (
                await receipt_reader.load_by_mutation_id(mutation_id)
                if mutation_id is not None
                else await receipt_reader.load(idempotency_key or "")
            )
        except ObsidianCheckpointRecoveryRequiredError:
            return MutationOutcomePolicy.unreadable_checkpoint_outcome(
                "note_write",
                idempotency_key,
                mutation_id,
            )
        if receipt is None:
            return ObsidianMutationOutcome(
                operation="note_write",
                idempotency_key=idempotency_key,
                mutation_id=mutation_id,
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                evidence=(MutationEvidenceCode.CHECKPOINT_ABSENT.value,),
            )
        if not receipt.effect_started:
            return receipt_outcome(
                receipt, evidence=(MutationEvidenceCode.EFFECT_NOT_STARTED.value,)
            )
        readback = await self._evidence_reader.read_path_if_present(
            receipt.canonical_path or ""
        )
        if isinstance(readback, OutcomeReadbackFailure):
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.UNKNOWN),
                evidence=(
                    MutationEvidenceCode.READBACK_FAILED.value,
                    readback.error_type,
                ),
            )
        try:
            return await receipts.observe(receipt, readback)
        except OSError, ObsidianDomainError, ValueError:
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.UNKNOWN),
                evidence=(MutationEvidenceCode.SOURCE_HASH_READBACK_FAILED.value,),
            )

    async def verified_upsert_outcome(
        self,
        idempotency_key: str,
    ) -> ObsidianMutationOutcome:
        """Resolve one verified-upsert key against its durable write fence."""
        try:
            loaded = await self._evidence_reader.load_verified_checkpoint(
                _VERIFIED_UPSERT_PREFIX + idempotency_key
            )
        except ObsidianCheckpointRecoveryRequiredError:
            return MutationOutcomePolicy.unreadable_checkpoint_outcome(
                "verified_upsert", idempotency_key
            )
        if loaded is None:
            # The write fence records intent before any durable mutation, so an
            # absent checkpoint proves the write never started.
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                evidence=(MutationEvidenceCode.CHECKPOINT_ABSENT.value,),
            )
        if loaded.state is ObsidianVerifiedCheckpointState.INTENT_RECORDED:
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                checkpoint_state=loaded.state.value,
                canonical_path=loaded.canonical_path,
                evidence=(MutationEvidenceCode.WRITE_NOT_STARTED.value,),
            )
        readback = await self._evidence_reader.read_path_if_present(
            loaded.canonical_path
        )
        if isinstance(readback, OutcomeReadbackFailure):
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                checkpoint_state=loaded.state.value,
                canonical_path=loaded.canonical_path,
                evidence=(
                    MutationEvidenceCode.READBACK_FAILED.value,
                    readback.error_type,
                ),
            )
        if loaded.state is ObsidianVerifiedCheckpointState.COMPLETED:
            return MutationOutcomePolicy.completed_verified_outcome(
                loaded, readback, idempotency_key
            )
        if loaded.state is ObsidianVerifiedCheckpointState.WRITE_STARTED:
            return MutationOutcomePolicy.write_started_outcome(
                loaded, readback, idempotency_key
            )
        return MutationOutcomePolicy.unknown_outcome_verified_outcome(
            loaded,
            readback,
            idempotency_key,
        )

    async def relate_outcome(self, idempotency_key: str) -> ObsidianMutationOutcome:
        """Resolve one relate key against its recorded relation evidence."""
        try:
            loaded = await self._evidence_reader.load_relate_checkpoint(
                _RELATE_PREFIX + idempotency_key
            )
        except ObsidianCheckpointRecoveryRequiredError:
            return MutationOutcomePolicy.unreadable_checkpoint_outcome(
                "relate", idempotency_key
            )
        if loaded is None:
            # Relate records its fence only after the mutation, so absence
            # cannot prove the relation never landed.
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                evidence=(MutationEvidenceCode.NO_RELATE_FENCE_RECORDED.value,),
            )
        try:
            source = await self._obsidian_service.read_note(loaded.source_note_id)
            target = await self._obsidian_service.read_note(loaded.target_note_id)
        except ObsidianNotFoundError:
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                operation_identity=checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
                checkpoint_state=loaded.result.completion_status.value,
                note_id=loaded.source_note_id,
                content_hash=loaded.source_content_hash,
                evidence=(MutationEvidenceCode.RECORDED_NOTE_MISSING.value,),
            )
        except (OSError, ObsidianDomainError) as exc:
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                operation_identity=checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                note_id=loaded.source_note_id,
                content_hash=loaded.source_content_hash,
                evidence=(
                    MutationEvidenceCode.READBACK_FAILED.value,
                    type(exc).__name__,
                ),
            )
        if not relation_present(source, target, loaded.relation):
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                operation_identity=checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
                checkpoint_state=loaded.result.completion_status.value,
                canonical_path=source.relative_path,
                note_id=source.note_id,
                content_hash=source.content_hash,
                version=_note_version(source),
                evidence=(MutationEvidenceCode.RECORDED_RELATION_ABSENT.value,),
            )
        evidence = [MutationEvidenceCode.RELATION_READBACK_VERIFIED.value]
        if (
            loaded.result.completion_status
            is not ObsidianRelateCompletionStatus.COMPLETED
        ):
            evidence.extend(
                issue.code for issue in (*loaded.result.warnings, *loaded.result.errors)
            )
        return ObsidianMutationOutcome(
            operation="relate",
            idempotency_key=idempotency_key,
            operation_identity=checkpoint_identity(loaded.request_hash),
            status=ObsidianMutationOutcomeStatus.COMMITTED,
            checkpoint_state=loaded.result.completion_status.value,
            canonical_path=source.relative_path,
            note_id=source.note_id,
            content_hash=source.content_hash,
            version=_note_version(source),
            committed_at=_aware_timestamp(source.modified_at),
            evidence=tuple(evidence),
        )
