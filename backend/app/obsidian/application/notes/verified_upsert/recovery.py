"""Recover verified-upsert source and projection outcomes from exact evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.obsidian.application.notes.verified_upsert.checkpoints import (
    VerifiedUpsertCheckpoints,
)
from app.obsidian.application.notes.verified_upsert.mapping import EvidenceMapper
from app.obsidian.application.notes.verified_upsert.obsidian_verified_upsert_policy import (
    verified_request_matches_note,
)
from app.obsidian.application.notes.verified_upsert.readback import (
    VerifiedUpsertReadback,
)
from app.obsidian.application.vault.index_errors import (
    index_error_code,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedProjectionStatus,
    ObsidianVerifiedUpsertCheckpoint,
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.obsidian.domain.verified_upsert_exceptions import (
    ObsidianVerifiedUpsertRecoveryRequiredError,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdentityConflictError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)


class VerifiedUpsertRecovery:
    """Own checkpoint recovery and compensation after one admitted mutation."""

    def __init__(
        self,
        readback: VerifiedUpsertReadback,
        checkpoints: VerifiedUpsertCheckpoints,
        mapper: EvidenceMapper,
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Bind existing recovery collaborators and the caller-owned rollback."""
        self._readback = readback
        self._checkpoints = checkpoints
        self._mapper = mapper
        self._rollback_projection = rollback_projection

    async def recover_checkpoint(
        self,
        request: ObsidianVerifiedUpsertRequest,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
    ) -> ObsidianVerifiedUpsertResult | None:
        """Resolve durable intent by exact readback before permitting a retry."""
        try:
            note = await self._readback.read_path_if_present(checkpoint.canonical_path)
        except ObsidianValidationError as error:
            if (
                checkpoint.state is ObsidianVerifiedCheckpointState.COMPLETED
                and index_error_code(error)
                in {
                    ObsidianIndexErrorCode.INVALID_CONTENT_HASH,
                    ObsidianIndexErrorCode.INVALID_CONTENT_INTEGRITY,
                }
            ):
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: completed replay source integrity drifted"
                ) from error
            raise
        if checkpoint.state is ObsidianVerifiedCheckpointState.COMPLETED:
            if note is None or checkpoint.note_id != note.note_id:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: completed replay source is missing "
                    "or has a different note id"
                )
            if checkpoint.content_hash != note.content_hash:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: completed replay source hash drifted"
                )
            if not verified_request_matches_note(request=request, note=note):
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: completed replay source payload drifted"
                )
            return self._mapper.from_note(
                request=request,
                note=note,
                operation=ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY,
                warnings=("durable_replay_readback_verified",),
            )

        if (
            checkpoint.state is ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME
            and "SOURCE_WRITE_OUTCOME_UNKNOWN" in checkpoint.warnings
        ):
            raise ObsidianVerifiedUpsertRecoveryRequiredError(
                idempotency_key=request.idempotency_key,
                canonical_path=checkpoint.canonical_path,
            )

        if note is None:
            if checkpoint.state is ObsidianVerifiedCheckpointState.INTENT_RECORDED:
                return None
            raise ObsidianVerifiedUpsertRecoveryRequiredError(
                idempotency_key=request.idempotency_key,
                canonical_path=checkpoint.canonical_path,
            )
        if (
            checkpoint.target_note_id is not None
            and checkpoint.target_note_id != note.note_id
        ):
            raise ObsidianIdentityConflictError(
                operation="verified_upsert_recovery",
                requested_note_id=checkpoint.target_note_id,
                requested_path=checkpoint.canonical_path,
                id_target_path=checkpoint.canonical_path,
                path_target_id=note.note_id,
                recommended_operation="resolve_identity",
            )
        if not verified_request_matches_note(request=request, note=note):
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: unknown-outcome readback found a "
                "different canonical source"
            )
        result = self._mapper.from_note(
            request=request,
            note=note,
            operation=(
                ObsidianVerifiedUpsertOperation.CREATED
                if checkpoint.target_note_id is None
                else ObsidianVerifiedUpsertOperation.UPDATED
            ),
            warnings=("unknown_outcome_readback_verified",),
        )
        await self._checkpoints.save_completed(
            store=store,
            checkpoint_key=checkpoint_key,
            request=request,
            request_hash=checkpoint.request_hash,
            note=note,
            warnings=result.warnings,
        )
        return result

    async def resolve_write_error(
        self,
        request: ObsidianVerifiedUpsertRequest,
        checkpoint_key: str,
        store: ObsidianReportBundleRunStore,
        intent: ObsidianVerifiedUpsertCheckpoint,
        error: Exception,
    ) -> ObsidianVerifiedUpsertResult:
        """Read exact source state after a low-level write failure."""
        await self.rollback_projection_safely()
        try:
            note = await self._readback.read_path_if_present(intent.canonical_path)
        except (OSError, ObsidianDomainError) as read_error:
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                warnings=("source_readback_failed",),
            )
            await self._checkpoints.save(
                store=store,
                checkpoint_key=checkpoint_key,
                checkpoint=unknown,
            )
            raise ObsidianValidationError(
                "VERIFIED_UPSERT_OUTCOME_UNKNOWN: source write and exact "
                "readback both require recovery"
            ) from read_error
        if note is not None and verified_request_matches_note(
            request=request,
            note=note,
        ):
            source_write_unknown = isinstance(error, OSError)
            warning_code = (
                "SOURCE_WRITE_OUTCOME_UNKNOWN"
                if source_write_unknown
                else "write_error_readback_verified"
            )
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                note_id=note.note_id,
                target_note_id=intent.target_note_id,
                content_hash=note.content_hash,
                version=self._mapper.note_version(note),
                warnings=(warning_code,),
            )
            await self._checkpoints.save(
                store=store,
                checkpoint_key=checkpoint_key,
                checkpoint=unknown,
            )
            return self._mapper.from_note(
                request=request,
                note=note,
                operation=(
                    ObsidianVerifiedUpsertOperation.CREATED
                    if intent.target_note_id is None
                    else ObsidianVerifiedUpsertOperation.UPDATED
                ),
                warnings=(warning_code,),
                readback_verified=True,
                storage_status=(
                    ObsidianVerifiedProjectionStatus.UNKNOWN
                    if source_write_unknown
                    else ObsidianVerifiedProjectionStatus.VERIFIED
                ),
                metadata_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                fts_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                graph_edge_index_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                graph_projection_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                error_code="PROJECTION_WRITE_FAILED",
            )
        unknown = replace(
            intent,
            state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
            note_id=None if note is None else note.note_id,
            content_hash=None if note is None else note.content_hash,
            version=None if note is None else self._mapper.note_version(note),
            warnings=("write_error_readback_drift",),
        )
        await self._checkpoints.save(
            store=store,
            checkpoint_key=checkpoint_key,
            checkpoint=unknown,
        )
        raise ObsidianValidationError(
            "VERIFIED_UPSERT_OUTCOME_UNKNOWN: source mutation outcome needs "
            "durable recovery readback"
        ) from error

    async def rollback_projection_safely(self) -> None:
        """Rollback projection after a failure without masking its root cause."""
        try:
            await self._rollback_projection()
        except Exception:
            # The original projection failure remains authoritative; checkpoints
            # keep the source outcome recoverable.
            return
