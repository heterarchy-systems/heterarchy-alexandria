"""Prepare and complete the typed managed-spec execution boundary."""

from __future__ import annotations

import hashlib
from datetime import date

from typing_extensions import TypedDict

from app.obsidian.application.service.managed_spec.managed_spec_failures import (
    _failure,
)
from app.obsidian.application.service.managed_spec.managed_spec_sources import (
    ManagedSpecSourceVerifier,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecCheckpoint,
    ManagedSpecCheckpointStore,
    ManagedSpecCompleteRequest,
    ManagedSpecCompleteResult,
    ManagedSpecEnvelope,
    ManagedSpecOutputWrite,
    ManagedSpecOutputWriter,
    ManagedSpecOutputWriteResult,
    ManagedSpecPrepareRequest,
    ManagedSpecPrepareResult,
)
from app.obsidian.domain.entities.managed_spec import (
    managed_spec_completion_request_hash,
    managed_spec_envelope_hash,
    managed_spec_prepare_request_hash,
)
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecCompletionStatus,
    ManagedSpecFailureCode,
    ManagedSpecPrepareStatus,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdentityConflictError,
    ObsidianWriteConflictError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONValue


class _ManagedSpecOutputIdentityPayload(TypedDict, closed=True):
    """Stable fields hashed to derive the canonical output idempotency key."""

    namespace: str
    project: str
    workflow: str
    logical_date: str
    entity: str
    edition: str | None


class ManagedSpecExecutionService:
    """Coordinate source verification, durable checkpoints, and output writes."""

    def __init__(
        self,
        source: ObsidianReadPort,
        checkpoint_store: ManagedSpecCheckpointStore,
        output_writer: ManagedSpecOutputWriter,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
    ) -> None:
        """Initialize the managed-spec trust boundary."""
        self._source_verifier = ManagedSpecSourceVerifier(source=source)
        self._checkpoint_store = checkpoint_store
        self._output_writer = output_writer
        self._index_maintenance_coordinator = index_maintenance_coordinator

    async def prepare(
        self,
        request: ManagedSpecPrepareRequest,
    ) -> ManagedSpecPrepareResult:
        """Prepare one managed specification under the shared writer lease."""
        async with self._index_maintenance_coordinator.operation(
            "managed_spec",
            wait=True,
        ):
            return await self._prepare_serialized(request)

    async def _prepare_serialized(
        self,
        request: ManagedSpecPrepareRequest,
    ) -> ManagedSpecPrepareResult:
        """Resolve exact policy/spec notes and persist an inert envelope."""
        _validate_logical_date(request.logical_date)
        request_hash = managed_spec_prepare_request_hash(
            spec_identity=request.spec_identity,
            logical_date=request.logical_date,
            idempotency_key=request.idempotency_key,
            execution_context=request.execution_context,
        )
        existing = await self._checkpoint_store.load(request.idempotency_key)
        if existing is not None:
            _require_same_prepare_request(
                checkpoint=existing,
                request_hash=request_hash,
            )
            current_envelope = await self._source_verifier.prepare_envelope(
                request=request
            )
            if managed_spec_envelope_hash(current_envelope) != existing.envelope_hash:
                raise _failure(
                    code=ManagedSpecFailureCode.SPEC_DRIFT,
                    cause=(
                        "canonical policy or execution specification changed after prepare"
                    ),
                    retryable=False,
                    safe_next_action="prepare a new envelope from the current canonical notes",
                    recommended_action="discard_stale_prepare_and_reprepare",
                )
            return ManagedSpecPrepareResult(
                status=ManagedSpecPrepareStatus.REPLAYED,
                envelope=existing.envelope,
                envelope_hash=existing.envelope_hash,
            )

        envelope = await self._source_verifier.prepare_envelope(request=request)
        envelope_hash = managed_spec_envelope_hash(envelope)
        checkpoint = ManagedSpecCheckpoint(
            idempotency_key=request.idempotency_key,
            prepare_request_hash=request_hash,
            envelope_hash=envelope_hash,
            envelope=envelope,
        )
        if await self._checkpoint_store.save_if_absent(checkpoint):
            return ManagedSpecPrepareResult(
                status=ManagedSpecPrepareStatus.PREPARED,
                envelope=envelope,
                envelope_hash=envelope_hash,
            )

        winner = await self._checkpoint_store.load(request.idempotency_key)
        if winner is None:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_READY,
                cause=(
                    "prepare checkpoint became unavailable after a concurrent admission"
                ),
                retryable=True,
                safe_next_action="read the prepare checkpoint and retry the same request",
                recommended_action="retry_prepare_after_durable_readback",
            )
        _require_same_prepare_request(checkpoint=winner, request_hash=request_hash)
        return ManagedSpecPrepareResult(
            status=ManagedSpecPrepareStatus.REPLAYED,
            envelope=winner.envelope,
            envelope_hash=winner.envelope_hash,
        )

    async def complete(
        self,
        request: ManagedSpecCompleteRequest,
    ) -> ManagedSpecCompleteResult:
        """Complete one managed specification under the shared writer lease."""
        async with self._index_maintenance_coordinator.operation(
            "managed_spec",
            wait=True,
        ):
            return await self._complete_serialized(request)

    async def _complete_serialized(
        self,
        request: ManagedSpecCompleteRequest,
    ) -> ManagedSpecCompleteResult:
        """Revalidate pinned sources and delegate one verified logical output."""
        checkpoint = await self._checkpoint_store.load(request.idempotency_key)
        if checkpoint is None:
            raise _failure(
                code=ManagedSpecFailureCode.PREPARE_REQUIRED,
                cause="no durable prepare envelope exists for this idempotency key",
                retryable=False,
                safe_next_action="call prepare with the exact policy and specification note ids",
                recommended_action="prepare_managed_spec",
            )
        if request.prepared_envelope_hash != checkpoint.envelope_hash:
            raise _failure(
                code=ManagedSpecFailureCode.ENVELOPE_MISMATCH,
                cause="completion does not reference the persisted prepare envelope",
                retryable=False,
                safe_next_action="use the envelope_hash returned by prepare",
                recommended_action="read_prepare_result_before_complete",
            )
        completion_hash = managed_spec_completion_request_hash(request=request)
        if checkpoint.output is not None:
            if checkpoint.completion_request_hash != completion_hash:
                raise _failure(
                    code=ManagedSpecFailureCode.IDEMPOTENCY_CONFLICT,
                    cause=(
                        "the logical execution already completed with different output data"
                    ),
                    retryable=False,
                    safe_next_action="read the completed output or choose a new logical execution",
                    recommended_action="do_not_retry_with_changed_output",
                )
            await self._source_verifier.revalidate(envelope=checkpoint.envelope)
            if checkpoint.output_request is None:
                raise _failure(
                    code=ManagedSpecFailureCode.OUTPUT_NOT_READY,
                    cause=(
                        "completed checkpoint has no immutable output request for readback"
                    ),
                    retryable=True,
                    safe_next_action="inspect the verified-upsert checkpoint before retrying",
                    recommended_action="recover_verified_output_checkpoint",
                )
            try:
                replayed_output = await self._output_writer.verified_upsert(
                    checkpoint.output_request
                )
            except (ObsidianWriteConflictError, ObsidianIdentityConflictError) as exc:
                raise _failure(
                    code=ManagedSpecFailureCode.OUTPUT_DRIFT,
                    cause="canonical output changed or disappeared after completion",
                    retryable=False,
                    safe_next_action="inspect the canonical logical output before retrying",
                    recommended_action="resolve_output_drift",
                ) from exc
            except ObsidianDomainError as exc:
                raise _failure(
                    code=ManagedSpecFailureCode.OUTPUT_NOT_READY,
                    cause="canonical output readback is unavailable after completion",
                    retryable=True,
                    safe_next_action="inspect output readiness and retry the same completion",
                    recommended_action="recover_verified_output_before_retry",
                ) from exc
            _require_verified_output(result=replayed_output)
            replay_checkpoint = ManagedSpecCheckpoint(
                idempotency_key=checkpoint.idempotency_key,
                prepare_request_hash=checkpoint.prepare_request_hash,
                envelope_hash=checkpoint.envelope_hash,
                envelope=checkpoint.envelope,
                output_request=checkpoint.output_request,
                completion_request_hash=checkpoint.completion_request_hash,
                output=replayed_output,
            )
            await self._checkpoint_store.save(replay_checkpoint)
            return ManagedSpecCompleteResult(
                status=ManagedSpecCompletionStatus.REPLAYED,
                envelope=checkpoint.envelope,
                envelope_hash=checkpoint.envelope_hash,
                output=replayed_output,
            )

        await self._source_verifier.revalidate(envelope=checkpoint.envelope)

        output_request = ManagedSpecOutputWrite(
            idempotency_key=_output_idempotency_key(checkpoint.envelope),
            logical_identity=checkpoint.envelope.logical_identity,
            title=request.output_title,
            body=request.output_body,
            spec_note_id=checkpoint.envelope.spec_identity.note_id,
            spec_version=checkpoint.envelope.spec_version,
            spec_content_hash=checkpoint.envelope.spec_content_hash,
            policy_note_id=checkpoint.envelope.policy_note_id,
            policy_version=checkpoint.envelope.policy_version,
            policy_content_hash=checkpoint.envelope.policy_content_hash,
            prepared_envelope_hash=checkpoint.envelope_hash,
            expected_content_hash=request.expected_output_content_hash,
        )
        output = await self._output_writer.verified_upsert(output_request)
        _require_verified_output(result=output)
        completed = ManagedSpecCheckpoint(
            idempotency_key=checkpoint.idempotency_key,
            prepare_request_hash=checkpoint.prepare_request_hash,
            envelope_hash=checkpoint.envelope_hash,
            envelope=checkpoint.envelope,
            output_request=output_request,
            completion_request_hash=completion_hash,
            output=output,
        )
        await self._checkpoint_store.save(completed)
        return ManagedSpecCompleteResult(
            status=ManagedSpecCompletionStatus.COMPLETED,
            envelope=checkpoint.envelope,
            envelope_hash=checkpoint.envelope_hash,
            output=output,
        )

    async def execute(
        self,
        request: ManagedSpecPrepareRequest | ManagedSpecCompleteRequest,
    ) -> ManagedSpecPrepareResult | ManagedSpecCompleteResult:
        """Dispatch one already-discriminated typed request."""
        if isinstance(request, ManagedSpecPrepareRequest):
            return await self.prepare(request)
        return await self.complete(request)


def _validate_logical_date(logical_date: str) -> None:
    """Require an ISO calendar date for stable output identity."""
    try:
        date.fromisoformat(logical_date)
    except ValueError as exc:
        raise _failure(
            code=ManagedSpecFailureCode.SPEC_CONFLICT,
            cause="logical_date must be an ISO calendar date",
            retryable=False,
            safe_next_action="send a YYYY-MM-DD logical date",
            recommended_action="correct_logical_date",
        ) from exc


def _output_idempotency_key(envelope: ManagedSpecEnvelope) -> str:
    """Derive stable output idempotency from logical identity, not caller key."""
    identity = envelope.logical_identity
    payload = _ManagedSpecOutputIdentityPayload(
        namespace="managed-spec-output-v1",
        project=identity.project,
        workflow=identity.report,
        logical_date=identity.date,
        entity=identity.entity,
        edition=identity.edition,
    )
    return (
        "managed-spec-output:"
        + hashlib.sha256(
            dumps_canonical_json(dict[str, JSONValue](payload))
        ).hexdigest()
    )


def _require_same_prepare_request(
    checkpoint: ManagedSpecCheckpoint,
    request_hash: str,
) -> None:
    """Fence a reused prepare key to the original typed input."""
    if checkpoint.prepare_request_hash != request_hash:
        raise _failure(
            code=ManagedSpecFailureCode.IDEMPOTENCY_CONFLICT,
            cause="idempotency key was reused for different managed-spec input",
            retryable=False,
            safe_next_action="use a new idempotency key for a different execution",
            recommended_action="choose_new_idempotency_key",
        )


def _require_verified_output(result: ManagedSpecOutputWriteResult) -> None:
    """Refuse to checkpoint an output without durable source/readback safety."""
    if not result.storage_durable or not result.readback_verified:
        raise _failure(
            code=ManagedSpecFailureCode.SPEC_NOT_READY,
            cause="verified output writer did not prove durable source readback",
            retryable=True,
            safe_next_action="inspect the writer checkpoint and read the canonical output",
            recommended_action="recover_verified_output_before_retry",
        )
    if not result.duplicate_safe:
        raise _failure(
            code=ManagedSpecFailureCode.SPEC_CONFLICT,
            cause="verified output writer could not prove logical duplicate safety",
            retryable=False,
            safe_next_action="inspect the existing logical output before retrying",
            recommended_action="resolve_logical_output_conflict",
        )
