"""Agent-facing verified logical note upsert over canonical Obsidian storage."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import partial
from typing import Final

import anyio
from pydantic import TypeAdapter

from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.notes.obsidian_verified_upsert_policy import (
    is_active_status,
    normalize_verified_upsert_request,
    verified_request_matches_note,
    verified_upsert_frontmatter,
    verified_upsert_request_hash,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault.obsidian_vault_lifecycle_service import (
    index_error_code,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedCheckpointState,
    ObsidianVerifiedDuplicateSafety,
    ObsidianVerifiedProjectionStatus,
    ObsidianVerifiedUpsertCheckpoint,
    ObsidianVerifiedUpsertOperation,
    ObsidianVerifiedUpsertRequest,
    ObsidianVerifiedUpsertResult,
    ObsidianVerifiedUpsertSelector,
    ObsidianVerifiedUpsertVerification,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianFrontmatterMode,
    ObsidianIndexErrorCode,
    ObsidianIndexStatus,
    ObsidianWriteMatchBy,
    ObsidianWriteMode,
    ObsidianWriteOperation,
)
from app.obsidian.domain.verified_upsert_exceptions import (
    ObsidianVerifiedUpsertRecoveryRequiredError,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
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
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
)

_CHECKPOINT_ADAPTER: Final[TypeAdapter[ObsidianVerifiedUpsertCheckpoint]] = TypeAdapter(
    ObsidianVerifiedUpsertCheckpoint
)
_CHECKPOINT_PREFIX: Final[str] = "verified-upsert:"


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
        self._obsidian_service = obsidian_service
        self._canonical_identity_service = canonical_identity_service
        self._vault_config_store = vault_config_store
        self._index_maintenance_coordinator = index_maintenance_coordinator
        self._commit_projection = commit_projection
        self._rollback_projection = rollback_projection

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
        return await self._verify_serialized(selector)

    async def _upsert_serialized(
        self,
        request: ObsidianVerifiedUpsertRequest,
    ) -> ObsidianVerifiedUpsertResult:
        normalized = normalize_verified_upsert_request(request)
        request_hash = verified_upsert_request_hash(normalized)
        checkpoint_key = _CHECKPOINT_PREFIX + normalized.idempotency_key
        store = self._run_store()
        checkpoint = await self._load_checkpoint(store, checkpoint_key)
        if checkpoint is not None:
            if checkpoint.request_hash != request_hash:
                raise ObsidianIdempotencyConflictError
            recovered = await self._recover_checkpoint(
                normalized,
                checkpoint,
                store,
                checkpoint_key,
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
        existing = await self._read_path_if_present(resolution.canonical_path)
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
            if verified_request_matches_note(normalized, existing):
                result = self._result_from_note(
                    normalized,
                    existing,
                    operation=ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY,
                    warnings=("logical_identity_replay",),
                )
                await self._save_completed(
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
        await self._save_checkpoint(store, checkpoint_key, intent)
        started = replace(
            intent,
            state=ObsidianVerifiedCheckpointState.WRITE_STARTED,
        )
        await self._save_checkpoint(store, checkpoint_key, started)
        command = self._write_command(
            normalized,
            canonical_path=resolution.canonical_path,
            existing=existing,
        )
        try:
            write_result = await self._obsidian_service.write_note(command)
        except (ObsidianWriteConflictError, ObsidianIdentityConflictError):
            await self._save_checkpoint(store, checkpoint_key, intent)
            raise
        except (OSError, ObsidianDomainError) as exc:
            return await self._resolve_write_error(
                request=normalized,
                checkpoint_key=checkpoint_key,
                store=store,
                intent=intent,
                error=exc,
            )

        try:
            await self._commit_projection()
        except Exception as exc:
            await self._rollback_after_projection_failure()
            source_readback: ObsidianNote | None = None
            try:
                candidate = await self._read_path_if_present(
                    write_result.note.relative_path
                )
                if candidate is not None and verified_request_matches_note(
                    normalized, candidate
                ):
                    source_readback = candidate
            except (OSError, ObsidianDomainError):
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
                version=_note_version(evidence_note),
                warnings=("projection_commit_failed",),
            )
            await self._save_checkpoint(store, checkpoint_key, unknown)
            degraded = self._result_from_note(
                normalized,
                evidence_note,
                operation=_operation_from_write_result(write_result.operation),
                warnings=("projection_commit_failed", str(exc)),
                readback_verified=source_readback is not None,
                metadata_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                fts_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                graph_edge_index_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                graph_projection_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
                error_code="PROJECTION_COMMIT_FAILED",
            )
            return degraded

        readback = await self._read_path_if_present(write_result.note.relative_path)
        if readback is None or readback.note_id != write_result.note.note_id:
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                note_id=write_result.note.note_id,
                target_note_id=intent.target_note_id,
                warnings=("source_readback_unavailable",),
            )
            await self._save_checkpoint(store, checkpoint_key, unknown)
            raise ObsidianValidationError(
                "VERIFIED_UPSERT_OUTCOME_UNKNOWN: source readback did not "
                "confirm the canonical note"
            )
        if not verified_request_matches_note(normalized, readback):
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                note_id=readback.note_id,
                target_note_id=intent.target_note_id,
                content_hash=readback.content_hash,
                version=_note_version(readback),
                warnings=("source_readback_drift",),
            )
            await self._save_checkpoint(store, checkpoint_key, unknown)
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: canonical source changed before "
                "verified readback"
            )

        operation = _operation_from_write_result(write_result.operation)
        result = self._result_from_note(
            normalized,
            readback,
            operation=operation,
            warnings=tuple(write_result.warnings),
            write_result_statuses=(
                write_result.metadata_status,
                write_result.fts_status,
                write_result.graph_edge_index_status,
                write_result.graph_projection_status,
            ),
        )
        await self._save_completed(
            store=store,
            checkpoint_key=checkpoint_key,
            request=normalized,
            request_hash=request_hash,
            note=readback,
            warnings=result.warnings,
        )
        return result

    async def _recover_checkpoint(
        self,
        request: ObsidianVerifiedUpsertRequest,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
    ) -> ObsidianVerifiedUpsertResult | None:
        """Resolve durable intent by exact readback before permitting a retry."""
        try:
            note = await self._read_path_if_present(checkpoint.canonical_path)
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
            if not verified_request_matches_note(request, note):
                raise ObsidianWriteConflictError(
                    "OBSIDIAN_WRITE_CONFLICT: completed replay source payload drifted"
                )
            return self._result_from_note(
                request,
                note,
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
        if not verified_request_matches_note(request, note):
            raise ObsidianWriteConflictError(
                "OBSIDIAN_WRITE_CONFLICT: unknown-outcome readback found a "
                "different canonical source"
            )
        result = self._result_from_note(
            request,
            note,
            operation=(
                ObsidianVerifiedUpsertOperation.CREATED
                if checkpoint.target_note_id is None
                else ObsidianVerifiedUpsertOperation.UPDATED
            ),
            warnings=("unknown_outcome_readback_verified",),
        )
        await self._save_completed(
            store=store,
            checkpoint_key=checkpoint_key,
            request=request,
            request_hash=checkpoint.request_hash,
            note=note,
            warnings=result.warnings,
        )
        return result

    async def _resolve_write_error(
        self,
        request: ObsidianVerifiedUpsertRequest,
        checkpoint_key: str,
        store: ObsidianReportBundleRunStore,
        intent: ObsidianVerifiedUpsertCheckpoint,
        error: Exception,
    ) -> ObsidianVerifiedUpsertResult:
        """Read exact source state after a low-level write failure."""
        await self._rollback_after_projection_failure()
        try:
            note = await self._read_path_if_present(intent.canonical_path)
        except (OSError, ObsidianDomainError) as read_error:
            unknown = replace(
                intent,
                state=ObsidianVerifiedCheckpointState.UNKNOWN_OUTCOME,
                warnings=("source_readback_failed",),
            )
            await self._save_checkpoint(store, checkpoint_key, unknown)
            raise ObsidianValidationError(
                "VERIFIED_UPSERT_OUTCOME_UNKNOWN: source write and exact "
                "readback both require recovery"
            ) from read_error
        if note is not None and verified_request_matches_note(request, note):
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
                version=_note_version(note),
                warnings=(warning_code,),
            )
            await self._save_checkpoint(store, checkpoint_key, unknown)
            return self._result_from_note(
                request,
                note,
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
            version=None if note is None else _note_version(note),
            warnings=("write_error_readback_drift",),
        )
        await self._save_checkpoint(store, checkpoint_key, unknown)
        raise ObsidianValidationError(
            "VERIFIED_UPSERT_OUTCOME_UNKNOWN: source mutation outcome needs "
            "durable recovery readback"
        ) from error

    async def _verify_serialized(
        self,
        selector: ObsidianVerifiedUpsertSelector,
    ) -> ObsidianVerifiedUpsertVerification:
        if selector.identity is not None:
            resolution = (
                await self._canonical_identity_service.resolve_logical_identity(
                    selector.identity
                )
            )
            if resolution.existing_note_id is None:
                return ObsidianVerifiedUpsertVerification(
                    source_readable=False,
                    canonical_identity_resolved=False,
                    indexed=False,
                    vector_current=None,
                    graph_current=None,
                    duplicate_safe=(
                        False
                        if resolution.resolution == "AMBIGUOUS_CANONICAL_IDENTITY"
                        else None
                    ),
                    temporal_authority_consistent=None,
                    note_id=None,
                    canonical_path=resolution.canonical_path,
                    content_hash=None,
                    version=None,
                    warnings=("logical_identity_not_found",),
                )
            note = await self._obsidian_service.read_note(resolution.existing_note_id)
            duplicate_safe = len(resolution.candidate_paths) <= 1
            canonical_resolved = resolution.resolution == "EXISTING_CANONICAL_FAMILY"
        elif selector.note_id is not None:
            note = await self._obsidian_service.read_note(selector.note_id)
            duplicate_safe = True
            canonical_resolved = True
        else:
            path = selector.path
            if path is None:
                raise ObsidianValidationError("verified upsert selector is empty")
            note = await self._obsidian_service.read_note_by_path(path)
            duplicate_safe = True
            canonical_resolved = True
        return ObsidianVerifiedUpsertVerification(
            source_readable=True,
            canonical_identity_resolved=canonical_resolved,
            indexed=note.index_status is ObsidianIndexStatus.INDEXED,
            vector_current=None,
            graph_current=None,
            duplicate_safe=duplicate_safe,
            temporal_authority_consistent=None,
            note_id=note.note_id,
            canonical_path=note.relative_path,
            content_hash=note.content_hash,
            version=_note_version(note),
        )

    def _write_command(
        self,
        request: ObsidianVerifiedUpsertRequest,
        canonical_path: str,
        existing: ObsidianNote | None,
    ) -> ObsidianWriteNote:
        """Build a canonical write without accepting caller-owned identity fields."""
        frontmatter = verified_upsert_frontmatter(request)
        payload = ObsidianSaveNote(
            title=request.title,
            body=request.body,
            alexandria_type=request.alexandria_type,
            note_id=None if existing is None else existing.note_id,
            relative_path=canonical_path,
            tags=request.tags,
            status="active",
            project=request.identity.project,
            source=request.source,
            frontmatter=frontmatter,
            expected_content_hash=request.expected_content_hash,
        )
        return ObsidianWriteNote(
            note=payload,
            write_mode=ObsidianWriteMode.UPSERT,
            match_by=ObsidianWriteMatchBy.PATH,
            frontmatter_mode=ObsidianFrontmatterMode.MERGE,
        )

    def _result_from_note(
        self,
        request: ObsidianVerifiedUpsertRequest,
        note: ObsidianNote,
        operation: ObsidianVerifiedUpsertOperation,
        warnings: tuple[str, ...] = (),
        write_result_statuses: tuple[str, str, str, str] | None = None,
        readback_verified: bool = True,
        metadata_status: ObsidianVerifiedProjectionStatus | None = None,
        fts_status: ObsidianVerifiedProjectionStatus | None = None,
        graph_edge_index_status: ObsidianVerifiedProjectionStatus | None = None,
        graph_projection_status: ObsidianVerifiedProjectionStatus | None = None,
        storage_status: ObsidianVerifiedProjectionStatus | None = None,
        error_code: str | None = None,
    ) -> ObsidianVerifiedUpsertResult:
        """Map canonical note evidence into the agent-facing result contract."""
        metadata = metadata_status or _metadata_status(note.index_status)
        if write_result_statuses is None:
            fts = fts_status or (
                ObsidianVerifiedProjectionStatus.VERIFIED
                if metadata is ObsidianVerifiedProjectionStatus.VERIFIED
                else ObsidianVerifiedProjectionStatus.UNKNOWN
            )
            graph_edge = (
                graph_edge_index_status or ObsidianVerifiedProjectionStatus.UNKNOWN
            )
            graph_projection = (
                graph_projection_status or ObsidianVerifiedProjectionStatus.UNKNOWN
            )
        else:
            _, fts_raw, edge_raw, projection_raw = write_result_statuses
            fts = fts_status or _projection_status(fts_raw)
            graph_edge = graph_edge_index_status or _projection_status(edge_raw)
            graph_projection = graph_projection_status or _projection_status(
                projection_raw
            )
        return ObsidianVerifiedUpsertResult(
            operation=operation,
            idempotency_key=request.idempotency_key,
            logical_identity=request.identity,
            note_id=note.note_id,
            canonical_path=note.relative_path,
            content_hash=note.content_hash,
            version=_note_version(note),
            storage_status=(
                storage_status or ObsidianVerifiedProjectionStatus.VERIFIED
            ),
            readback_verified=readback_verified,
            metadata_status=metadata,
            fts_status=fts,
            vector_status=ObsidianVerifiedProjectionStatus.UNKNOWN,
            graph_edge_index_status=graph_edge,
            graph_projection_status=graph_projection,
            duplicate_safety=ObsidianVerifiedDuplicateSafety.VERIFIED,
            warnings=warnings,
            error_code=error_code,
        )

    async def _save_completed(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
        request: ObsidianVerifiedUpsertRequest,
        request_hash: str,
        note: ObsidianNote,
        warnings: tuple[str, ...],
    ) -> None:
        """Persist the completed source fence after verified readback."""
        checkpoint = ObsidianVerifiedUpsertCheckpoint(
            state=ObsidianVerifiedCheckpointState.COMPLETED,
            request_hash=request_hash,
            logical_identity=request.identity,
            canonical_path=note.relative_path,
            title=request.title,
            body_hash=hash_text(request.body),
            expected_content_hash=request.expected_content_hash,
            note_id=note.note_id,
            target_note_id=note.note_id,
            content_hash=note.content_hash,
            version=_note_version(note),
            warnings=warnings,
        )
        await self._save_checkpoint(store, checkpoint_key, checkpoint)

    async def _load_checkpoint(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
    ) -> ObsidianVerifiedUpsertCheckpoint | None:
        """Load the local checkpoint through the bounded blocking-I/O lane."""
        return await anyio.to_thread.run_sync(
            partial(
                store.load_typed,
                checkpoint_key,
                _CHECKPOINT_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def _save_checkpoint(
        self,
        store: ObsidianReportBundleRunStore,
        checkpoint_key: str,
        checkpoint: ObsidianVerifiedUpsertCheckpoint,
    ) -> None:
        """Save the local checkpoint through the bounded blocking-I/O lane."""
        await anyio.to_thread.run_sync(
            partial(
                store.save_typed,
                checkpoint_key,
                checkpoint,
                _CHECKPOINT_ADAPTER,
            ),
            limiter=anyio.to_thread.current_default_thread_limiter(),
        )

    async def _read_path_if_present(self, path: str) -> ObsidianNote | None:
        """Read one exact canonical path, preserving the not-found distinction."""
        try:
            return await self._obsidian_service.read_note_by_path(path)
        except ObsidianNotFoundError:
            return None

    async def _rollback_after_projection_failure(self) -> None:
        """Rollback the request transaction before exposing degraded evidence."""
        try:
            await self._rollback_projection()
        except Exception:
            # The original projection commit failure remains the authoritative
            # signal; the checkpoint keeps the source outcome recoverable.
            return

    def _run_store(self) -> ObsidianReportBundleRunStore:
        """Return the existing report-bundle checkpoint authority."""
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )


def _note_version(note: ObsidianNote) -> int | None:
    """Read the explicit canonical version from note frontmatter."""
    value = note.frontmatter.get("version")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _operation_from_write_result(
    operation: ObsidianWriteOperation,
) -> ObsidianVerifiedUpsertOperation:
    """Map low-level write observation to the high-level operation contract."""
    if operation is ObsidianWriteOperation.CREATED:
        return ObsidianVerifiedUpsertOperation.CREATED
    if operation is ObsidianWriteOperation.UPDATED:
        return ObsidianVerifiedUpsertOperation.UPDATED
    return ObsidianVerifiedUpsertOperation.IDEMPOTENT_REPLAY


def _metadata_status(
    index_status: ObsidianIndexStatus,
) -> ObsidianVerifiedProjectionStatus:
    """Map canonical index evidence into the high-level metadata status."""
    if index_status is ObsidianIndexStatus.INDEXED:
        return ObsidianVerifiedProjectionStatus.VERIFIED
    if index_status is ObsidianIndexStatus.STALE:
        return ObsidianVerifiedProjectionStatus.STALE
    return ObsidianVerifiedProjectionStatus.UNAVAILABLE


def _projection_status(value: str) -> ObsidianVerifiedProjectionStatus:
    """Map an existing low-level projection status without fabricating readiness."""
    normalized = value.casefold()
    if normalized in {"indexed", "ready", "verified", "stored"}:
        return ObsidianVerifiedProjectionStatus.VERIFIED
    if normalized == "pending":
        return ObsidianVerifiedProjectionStatus.PENDING
    if normalized == "unknown":
        return ObsidianVerifiedProjectionStatus.UNKNOWN
    if normalized in {"stale", "reindex_required"}:
        return ObsidianVerifiedProjectionStatus.STALE
    if normalized in {"unavailable", "failed", "error"}:
        return ObsidianVerifiedProjectionStatus.UNAVAILABLE
    return ObsidianVerifiedProjectionStatus.UNKNOWN
