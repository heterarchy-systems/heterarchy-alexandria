"""Read-only mutation outcome evidence for fenced logical writes.

After a lost mutation response (HTTP 0 / timeout), agents must not retry
blindly. This service answers "did this idempotency key commit?" from the
durable fence each write records and one exact canonical readback, without
mutating any state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.application.service.notes.obsidian_note_mutation_receipts import (
    NoteMutationReceipts,
    receipt_outcome,
)
from app.obsidian.application.service.notes.obsidian_relation_mutation_service import (
    relation_present,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedUpsertCheckpoint,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    MutationOperationKind,
    ObsidianMutationOutcome,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateCheckpoint
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.domain.event_enum.obsidian_relation_enums import (
    ObsidianRelateCompletionStatus,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
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

_VERIFIED_UPSERT_ADAPTER = TypeAdapter(ObsidianVerifiedUpsertCheckpoint)
_RELATE_ADAPTER = TypeAdapter(ObsidianRelateCheckpoint)


@dataclass(frozen=True, slots=True)
class _ReadbackFailure:
    """Marker for a canonical readback that could not be completed."""

    error_type: str


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
        try:
            receipt = (
                await receipts.load_by_mutation_id(mutation_id)
                if mutation_id is not None
                else await receipts.load(idempotency_key or "")
            )
        except ObsidianCheckpointRecoveryRequiredError:
            return self._unreadable_checkpoint_outcome(
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
                evidence=("checkpoint_absent",),
            )
        if not receipt.effect_started:
            return receipt_outcome(receipt, evidence=("effect_not_started",))
        readback = await self._read_path_if_present(receipt.canonical_path or "")
        if isinstance(readback, _ReadbackFailure):
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.UNKNOWN),
                evidence=("readback_failed", readback.error_type),
            )
        try:
            return await receipts.observe(receipt, readback)
        except (OSError, ObsidianDomainError, ValueError):
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.UNKNOWN),
                evidence=("source_hash_readback_failed",),
            )

    async def verified_upsert_outcome(
        self,
        idempotency_key: str,
    ) -> ObsidianMutationOutcome:
        """Resolve one verified-upsert key against its durable write fence."""
        try:
            loaded = await self._load_verified_checkpoint(
                _VERIFIED_UPSERT_PREFIX + idempotency_key
            )
        except ObsidianCheckpointRecoveryRequiredError:
            return self._unreadable_checkpoint_outcome(
                "verified_upsert", idempotency_key
            )
        if loaded is None:
            # The write fence records intent before any durable mutation, so an
            # absent checkpoint proves the write never started.
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                evidence=("checkpoint_absent",),
            )
        if loaded.state is ObsidianVerifiedCheckpointState.INTENT_RECORDED:
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                checkpoint_state=loaded.state.value,
                canonical_path=loaded.canonical_path,
                evidence=("write_not_started",),
            )
        readback = await self._read_path_if_present(loaded.canonical_path)
        if isinstance(readback, _ReadbackFailure):
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                checkpoint_state=loaded.state.value,
                canonical_path=loaded.canonical_path,
                evidence=("readback_failed", readback.error_type),
            )
        if loaded.state is ObsidianVerifiedCheckpointState.COMPLETED:
            return self._completed_verified_outcome(loaded, readback, idempotency_key)
        if loaded.state is ObsidianVerifiedCheckpointState.WRITE_STARTED:
            return self._write_started_outcome(loaded, readback, idempotency_key)
        return self._unknown_outcome_verified_outcome(
            loaded,
            readback,
            idempotency_key,
        )

    async def relate_outcome(self, idempotency_key: str) -> ObsidianMutationOutcome:
        """Resolve one relate key against its recorded relation evidence."""
        try:
            loaded = await self._load_relate_checkpoint(
                _RELATE_PREFIX + idempotency_key
            )
        except ObsidianCheckpointRecoveryRequiredError:
            return self._unreadable_checkpoint_outcome("relate", idempotency_key)
        if loaded is None:
            # Relate records its fence only after the mutation, so absence
            # cannot prove the relation never landed.
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                evidence=("no_relate_fence_recorded",),
            )
        try:
            source = await self._obsidian_service.read_note(loaded.source_note_id)
            target = await self._obsidian_service.read_note(loaded.target_note_id)
        except ObsidianNotFoundError:
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
                checkpoint_state=loaded.result.completion_status.value,
                note_id=loaded.source_note_id,
                content_hash=loaded.source_content_hash,
                evidence=("recorded_note_missing",),
            )
        except (OSError, ObsidianDomainError) as exc:
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                note_id=loaded.source_note_id,
                content_hash=loaded.source_content_hash,
                evidence=("readback_failed", type(exc).__name__),
            )
        if not relation_present(source, target, loaded.relation):
            return ObsidianMutationOutcome(
                operation="relate",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(loaded.request_hash),
                status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
                checkpoint_state=loaded.result.completion_status.value,
                canonical_path=source.relative_path,
                note_id=source.note_id,
                content_hash=source.content_hash,
                version=_note_version(source),
                evidence=("recorded_relation_absent",),
            )
        evidence = ["relation_readback_verified"]
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
            operation_identity=_checkpoint_identity(loaded.request_hash),
            status=ObsidianMutationOutcomeStatus.COMMITTED,
            checkpoint_state=loaded.result.completion_status.value,
            canonical_path=source.relative_path,
            note_id=source.note_id,
            content_hash=source.content_hash,
            version=_note_version(source),
            committed_at=_aware_timestamp(source.modified_at),
            evidence=tuple(evidence),
        )

    def _completed_verified_outcome(
        self,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
        readback: ObsidianNote | None,
        idempotency_key: str,
    ) -> ObsidianMutationOutcome:
        """Judge a completed fence against the exact canonical source."""
        if readback is None or readback.note_id != checkpoint.note_id:
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(checkpoint.request_hash),
                status=ObsidianMutationOutcomeStatus.CONFLICTED,
                checkpoint_state=checkpoint.state.value,
                canonical_path=checkpoint.canonical_path,
                note_id=checkpoint.note_id,
                content_hash=checkpoint.content_hash,
                version=checkpoint.version,
                evidence=("completed_source_missing_or_replaced",),
            )
        if readback.content_hash != checkpoint.content_hash:
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(checkpoint.request_hash),
                status=ObsidianMutationOutcomeStatus.CONFLICTED,
                checkpoint_state=checkpoint.state.value,
                canonical_path=readback.relative_path,
                note_id=readback.note_id,
                content_hash=readback.content_hash,
                version=_note_version(readback),
                evidence=("completed_source_drift",),
            )
        return ObsidianMutationOutcome(
            operation="verified_upsert",
            idempotency_key=idempotency_key,
            operation_identity=_checkpoint_identity(checkpoint.request_hash),
            status=ObsidianMutationOutcomeStatus.COMMITTED,
            checkpoint_state=checkpoint.state.value,
            canonical_path=readback.relative_path,
            note_id=readback.note_id,
            content_hash=readback.content_hash,
            version=_note_version(readback),
            committed_at=_aware_timestamp(readback.modified_at),
            evidence=("durable_checkpoint_readback_verified",),
        )

    def _write_started_outcome(
        self,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
        readback: ObsidianNote | None,
        idempotency_key: str,
    ) -> ObsidianMutationOutcome:
        """Attribute a started write through exact source evidence."""
        if readback is None:
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(checkpoint.request_hash),
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                checkpoint_state=checkpoint.state.value,
                canonical_path=checkpoint.canonical_path,
                evidence=("target_path_absent",),
            )
        if (
            checkpoint.target_note_id is not None
            and readback.note_id != checkpoint.target_note_id
        ):
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(checkpoint.request_hash),
                status=ObsidianMutationOutcomeStatus.CONFLICTED,
                checkpoint_state=checkpoint.state.value,
                canonical_path=readback.relative_path,
                note_id=readback.note_id,
                content_hash=readback.content_hash,
                version=_note_version(readback),
                evidence=("identity_drift",),
            )
        if (
            checkpoint.expected_content_hash is not None
            and readback.content_hash == checkpoint.expected_content_hash
        ):
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(checkpoint.request_hash),
                status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
                checkpoint_state=checkpoint.state.value,
                canonical_path=readback.relative_path,
                note_id=readback.note_id,
                content_hash=readback.content_hash,
                version=_note_version(readback),
                evidence=("cas_target_unchanged",),
            )
        return ObsidianMutationOutcome(
            operation="verified_upsert",
            idempotency_key=idempotency_key,
            operation_identity=_checkpoint_identity(checkpoint.request_hash),
            status=ObsidianMutationOutcomeStatus.UNKNOWN,
            checkpoint_state=checkpoint.state.value,
            canonical_path=readback.relative_path,
            note_id=readback.note_id,
            content_hash=readback.content_hash,
            version=_note_version(readback),
            evidence=("outcome_not_attributable",),
        )

    def _unknown_outcome_verified_outcome(
        self,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
        readback: ObsidianNote | None,
        idempotency_key: str,
    ) -> ObsidianMutationOutcome:
        """Judge a recorded indeterminate outcome by its captured evidence."""
        if checkpoint.content_hash is not None:
            if (
                readback is not None
                and readback.content_hash == checkpoint.content_hash
            ):
                return ObsidianMutationOutcome(
                    operation="verified_upsert",
                    idempotency_key=idempotency_key,
                    operation_identity=_checkpoint_identity(checkpoint.request_hash),
                    status=ObsidianMutationOutcomeStatus.COMMITTED,
                    checkpoint_state=checkpoint.state.value,
                    canonical_path=readback.relative_path,
                    note_id=readback.note_id,
                    content_hash=readback.content_hash,
                    version=_note_version(readback),
                    committed_at=_aware_timestamp(readback.modified_at),
                    evidence=(
                        "recorded_content_readback_verified",
                        *checkpoint.warnings,
                    ),
                )
            return ObsidianMutationOutcome(
                operation="verified_upsert",
                idempotency_key=idempotency_key,
                operation_identity=_checkpoint_identity(checkpoint.request_hash),
                status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
                checkpoint_state=checkpoint.state.value,
                canonical_path=checkpoint.canonical_path,
                note_id=checkpoint.note_id,
                content_hash=checkpoint.content_hash,
                version=checkpoint.version,
                evidence=("recorded_content_not_confirmed", *checkpoint.warnings),
            )
        return ObsidianMutationOutcome(
            operation="verified_upsert",
            idempotency_key=idempotency_key,
            operation_identity=_checkpoint_identity(checkpoint.request_hash),
            status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
            checkpoint_state=checkpoint.state.value,
            canonical_path=checkpoint.canonical_path,
            note_id=checkpoint.note_id,
            content_hash=checkpoint.content_hash,
            version=checkpoint.version,
            evidence=("recorded_outcome_requires_recovery", *checkpoint.warnings),
        )

    def _unreadable_checkpoint_outcome(
        self,
        operation: MutationOperationKind,
        idempotency_key: str | None,
        mutation_id: str | None = None,
    ) -> ObsidianMutationOutcome:
        """Report an unreadable fence as requiring durable recovery."""
        return ObsidianMutationOutcome(
            operation=operation,
            idempotency_key=idempotency_key,
            mutation_id=mutation_id,
            status=ObsidianMutationOutcomeStatus.RECONCILIATION_REQUIRED,
            evidence=("checkpoint_unreadable_requires_recovery",),
        )

    def _run_store(self) -> ObsidianReportBundleRunStore:
        """Return the existing report-bundle checkpoint authority."""
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )

    async def _load_verified_checkpoint(
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

    async def _load_relate_checkpoint(
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

    async def _read_path_if_present(
        self,
        path: str,
    ) -> ObsidianNote | _ReadbackFailure | None:
        """Read one exact canonical path, distinguishing not-found from failure."""
        try:
            return await self._obsidian_service.read_note_by_path(path)
        except ObsidianNotFoundError:
            return None
        except (OSError, ObsidianDomainError) as exc:
            return _ReadbackFailure(error_type=type(exc).__name__)


def _note_version(note: ObsidianNote) -> int | None:
    """Read the explicit canonical version from note frontmatter."""
    value = note.frontmatter.get("version")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _checkpoint_identity(value: str | None) -> str | None:
    """Expose only a well-formed durable outer request fingerprint."""
    if value is None or len(value) != 64:
        return None
    return (
        value if all(character in "0123456789abcdef" for character in value) else None
    )


def _aware_timestamp(value: datetime | None) -> datetime | None:
    """Expose source timestamps only when they carry an explicit timezone."""
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value
