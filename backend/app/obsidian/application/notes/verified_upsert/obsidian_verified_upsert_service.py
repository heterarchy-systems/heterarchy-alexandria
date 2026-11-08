"""Agent-facing verified logical note upsert over canonical Obsidian storage."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.obsidian.application.notes.verified_upsert.checkpoints import (
    _CHECKPOINT_PREFIX,
    VerifiedUpsertCheckpoints,
)
from app.obsidian.application.notes.verified_upsert.mapping import (
    EvidenceMapper,
    build_write_command,
)
from app.obsidian.application.notes.verified_upsert.obsidian_verified_upsert_policy import (
    is_active_status,
    normalize_verified_upsert_request,
    verified_request_matches_note,
    verified_upsert_request_hash,
)
from app.obsidian.application.notes.verified_upsert.readback import (
    VerifiedUpsertReadback,
)
from app.obsidian.application.notes.verified_upsert.recovery import (
    VerifiedUpsertRecovery,
)
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedProjectionStatus,
    ObsidianVerifiedUpsertCheckpoint,
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertResult,
    ObsidianVerifiedUpsertSelector,
    ObsidianVerifiedUpsertVerification,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdempotencyConflictError,
    ObsidianIdentityConflictError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)


class ObsidianVerifiedUpsertService:
    """Coordinate logical identity, canonical write, readback, and replay fencing."""

    def __init__(
        self,
        obsidian_service: ObsidianService,
        canonical_identity_service: ObsidianCanonicalIdentityService,
        vault_config_store: ObsidianVaultConfigStore,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the verified upsert application boundary."""
        mapper = EvidenceMapper()
        self._obsidian_service = obsidian_service
        self._canonical_identity_service = canonical_identity_service
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._commit_projection = commit_projection
        self._mapper = mapper
        self._checkpoints = VerifiedUpsertCheckpoints(
            vault_config_store=vault_config_store,
            mapper=mapper,
        )
        self._readback = VerifiedUpsertReadback(
            obsidian_service=obsidian_service,
            canonical_identity_service=canonical_identity_service,
            mapper=mapper,
        )
        self._recovery = VerifiedUpsertRecovery(
            readback=self._readback,
            checkpoints=self._checkpoints,
            mapper=mapper,
            rollback_projection=rollback_projection,
        )

    async def upsert(
        self,
        request: ObsidianVerifiedUpsertRequest,
    ) -> ObsidianVerifiedUpsertResult:
        """Perform one serialized logical upsert with durable replay fencing."""
        async with self._index_maintenance_coordinator.operation(
            "obsidian_verified_upsert",
            wait=True,
        ):
            return await self._upsert_serialized(request)

    async def verify(
        self,
        selector: ObsidianVerifiedUpsertSelector,
    ) -> ObsidianVerifiedUpsertVerification:
        """Diagnose source, identity, index, and duplicate evidence in one read."""
        return await self._readback.verify(selector)

    async def _upsert_serialized(
        self,
        request: ObsidianVerifiedUpsertRequest,
    ) -> ObsidianVerifiedUpsertResult:
        normalized = normalize_verified_upsert_request(request)
        request_hash = verified_upsert_request_hash(normalized)
        checkpoint_key = _CHECKPOINT_PREFIX + normalized.idempotency_key
        store = self._checkpoints.open_store()
        checkpoint = await self._checkpoints.load(
            store=store,
            checkpoint_key=checkpoint_key,
        )
        if checkpoint is not None:
            if checkpoint.request_hash != request_hash:
                raise ObsidianIdempotencyConflictError
            recovered = await self._recovery.recover_checkpoint(
                request=normalized,
                checkpoint=checkpoint,
                store=store,
                checkpoint_key=checkpoint_key,
            )
            if recovered is not None:
                return recovered

        resolution = await self._canonical_identity_service.resolve_logical_identity(
            normalized.identity
        )
        if resolution.resolution == "AMBIGUOUS_CANONICAL_IDENTITY":
            raise ObsidianIdentityConflictError(
                operation="verified_upsert",
                requested_note_id=None,
                requested_path=resolution.canonical_path,
                id_target_path=None,
                path_target_id=None,
                recommended_operation="resolve_identity",
            )
        existing = await self._readback.read_existing_for_resolution(resolution)
        if existing is not None and resolution.existing_note_id is None:
            raise ObsidianIdentityConflictError(
                operation="verified_upsert",
                requested_note_id=None,
                requested_path=resolution.canonical_path,
                id_target_path=existing.relative_path,
                path_target_id=existing.note_id,
                recommended_operation="resolve_identity",
            )
        if resolution.existing_note_id is not None:
            if existing is None or existing.note_id != resolution.existing_note_id:
                existing = await self._obsidian_service.read_note(
                    resolution.existing_note_id
                )
            if not is_active_status(existing.status):
                raise ObsidianIdentityConflictError(
                    operation="verified_upsert",
                    requested_note_id=existing.note_id,
                    requested_path=existing.relative_path,
                    id_target_path=existing.relative_path,
                    path_target_id=existing.note_id,
                    recommended_operation="resolve_identity",
                )

        if existing is not None:
            if verified_request_matches_note(request=normalized, note=existing):
                existing = await self._readback.verify_replay_candidate(
                    resolution=resolution,
                    existing=existing,
                )
                if existing is None:
                    raise ObsidianWriteConflictError(
                        "OBSIDIAN_WRITE_CONFLICT: canonical replay source disappeared "
                        "after identity resolution"
                    )
                if verified_request_matches_note(normalized, existing):
                    result = self._mapper.from_note(
                        request=normalized,
                        note=existing,
                        operation=ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY,
                        warnings=("logical_identity_replay",),
                    )
                    await self._checkpoints.save_completed(
                        store=store,
                        checkpoint_key=checkpoint_key,
                        request=normalized,
                        request_hash=request_hash,
                        note=existing,
                        warnings=result.warnings,
                    )
                    return result
            if normalized.expected_content_hash is None:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: logical identity already has "
                    "different active content; expected_content_hash is required"
                )
            if existing.content_hash != normalized.expected_content_hash:
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: expected content hash does not "
                    "match the active logical note"
                )

        intent = ObsidianVerifiedUpsertCheckpoint(
            state=ObsidianVerifiedCheckpointState.INTENT_RECORDED,
            request_hash=request_hash,
            logical_identity=normalized.identity,
            canonical_path=resolution.canonical_path,
            title=normalized.title.strip(),
            body_hash=hash_text(normalized.body),
            expected_content_hash=normalized.expected_content_hash,
            target_note_id=None if existing is None else existing.note_id,
        )
        await self._checkpoints.save(
            store=store,
            checkpoint_key=checkpoint_key,
            checkpoint=intent,
        )
        started = replace(
            intent,
            state=ObsidianVerifiedCheckpointState.WRITE_STARTED,
        )
        await self._checkpoints.save(
            store=store,
            checkpoint_key=checkpoint_key,
            checkpoint=started,
        )
        command = build_write_command(
            request=normalized,
            canonical_path=resolution.canonical_path,
            existing=existing,
        )
        try:
            write_result = await self._obsidian_service.write_note(command)
        except ObsidianWriteConflictError, ObsidianIdentityConflictError:
            await self._checkpoints.save(
                store=store,
                checkpoint_key=checkpoint_key,
                checkpoint=intent,
            )
            raise
        except (OSError, ObsidianDomainError) as exc:
            return await self._recovery.resolve_write_error(
                request=normalized,
                checkpoint_key=checkpoint_key,
                store=store,
                intent=intent,
                error=exc,
            )

        try:
            await self._commit_projection()
        except Exception as exc:
            await self._recovery.rollback_projection_safely()
            source_readback: ObsidianNote | None = None
            try:
                candidate = await self._readback.read_path_if_present(
                    write_result.note.relative_path
                )
                if candidate is not None and verified_request_matches_note(
                    request=normalized,
                    note=candidate,
                ):
                    source_readback = candidate
            except OSError, ObsidianDomainError:
                source_readback = None
            evidence_note = (
                write_result.note if source_readback is None else source_readback
            )
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                note_id=evidence_note.note_id,
                target_note_id=intent.target_note_id,
                content_hash=evidence_note.content_hash,
                version=self._mapper.note_version(evidence_note),
                warnings=("projection_commit_failed",),
            )
            await self._checkpoints.save(
                store=store,
                checkpoint_key=checkpoint_key,
                checkpoint=unknown,
            )
            degraded = self._mapper.from_note(
                request=normalized,
                note=evidence_note,
                operation=self._mapper.operation_from_write_result(
                    write_result.operation
                ),
                warnings=("projection_commit_failed", str(exc)),
                readback_verified=source_readback is not None,
                metadata_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                fts_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                graph_edge_index_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                graph_projection_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                error_code="PROJECTION_COMMIT_FAILED",
            )
            return degraded

        readback = await self._readback.verified_post_commit_readback(write_result)
        if readback is None or readback.note_id != write_result.note.note_id:
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                note_id=write_result.note.note_id,
                target_note_id=intent.target_note_id,
                warnings=("source_readback_unavailable",),
            )
            await self._checkpoints.save(
                store=store,
                checkpoint_key=checkpoint_key,
                checkpoint=unknown,
            )
            raise ObsidianValidationError(
                "VERIFIED_UPSERT_OUTCOME_UNKNOWN: source readback did not "
                "confirm the canonical note"
            )
        if not verified_request_matches_note(request=normalized, note=readback):
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                note_id=readback.note_id,
                target_note_id=intent.target_note_id,
                content_hash=readback.content_hash,
                version=self._mapper.note_version(readback),
                warnings=("source_readback_drift",),
            )
            await self._checkpoints.save(
                store=store,
                checkpoint_key=checkpoint_key,
                checkpoint=unknown,
            )
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: canonical source changed before "
                "verified readback"
            )

        operation = self._mapper.operation_from_write_result(write_result.operation)
        result = self._mapper.from_note(
            request=normalized,
            note=readback,
            operation=operation,
            warnings=tuple(write_result.warnings),
            write_result_statuses=(
                write_result.metadata_status,
                write_result.fts_status,
                write_result.graph_edge_index_status,
                write_result.graph_projection_status,
            ),
        )
        await self._checkpoints.save_completed(
            store=store,
            checkpoint_key=checkpoint_key,
            request=normalized,
            request_hash=request_hash,
            note=readback,
            warnings=result.warnings,
        )
        return result
