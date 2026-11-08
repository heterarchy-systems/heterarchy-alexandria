"""Pure classifications for durable mutation outcome evidence."""

from __future__ import annotations

from datetime import datetime

from app.obsidian.application.notes.mutations.mutation_evidence_enums import (
    MutationEvidenceCode,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedUpsertCheckpoint,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    MutationOperationKind,
    ObsidianMutationOutcome,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)


class MutationOutcomePolicy:
    """Build truthful mutation outcome records from observed evidence."""

    @staticmethod
    def completed_verified_outcome(
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
                evidence=(
                    MutationEvidenceCode.COMPLETED_SOURCE_MISSING_OR_REPLACED.value,
                ),
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
                evidence=(MutationEvidenceCode.COMPLETED_SOURCE_DRIFT.value,),
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
            evidence=(MutationEvidenceCode.DURABLE_CHECKPOINT_READBACK_VERIFIED.value,),
        )

    @staticmethod
    def write_started_outcome(
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
                evidence=(MutationEvidenceCode.TARGET_PATH_ABSENT.value,),
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
                evidence=(MutationEvidenceCode.IDENTITY_DRIFT.value,),
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
                evidence=(MutationEvidenceCode.CAS_TARGET_UNCHANGED.value,),
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
            evidence=(MutationEvidenceCode.OUTCOME_NOT_ATTRIBUTABLE.value,),
        )

    @staticmethod
    def unknown_outcome_verified_outcome(
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
                        MutationEvidenceCode.RECORDED_CONTENT_READBACK_VERIFIED.value,
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
                evidence=(
                    MutationEvidenceCode.RECORDED_CONTENT_NOT_CONFIRMED.value,
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
            evidence=(
                MutationEvidenceCode.RECORDED_OUTCOME_REQUIRES_RECOVERY.value,
                *checkpoint.warnings,
            ),
        )

    @staticmethod
    def unreadable_checkpoint_outcome(
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
            evidence=(
                MutationEvidenceCode.CHECKPOINT_UNREADABLE_REQUIRES_RECOVERY.value,
            ),
        )


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
