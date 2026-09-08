"""Prepare and complete the typed managed-spec execution boundary."""

from __future__ import annotations

import hashlib
from datetime import date

from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecCheckpoint,
    ManagedSpecCheckpointStore,
    ManagedSpecCompleteRequest,
    ManagedSpecCompleteResult,
    ManagedSpecEnvelope,
    ManagedSpecExecutionContext,
    ManagedSpecIdentity,
    ManagedSpecOutputWrite,
    ManagedSpecOutputWriter,
    ManagedSpecOutputWriteResult,
    ManagedSpecPrepareRequest,
    ManagedSpecPrepareResult,
)
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.entities.managed_spec import (
    managed_spec_completion_request_hash,
    managed_spec_envelope_hash,
    managed_spec_prepare_request_hash,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecCompletionStatus,
    ManagedSpecFailureCode,
    ManagedSpecPrepareStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)
from app.obsidian.domain.managed_spec_exceptions import ManagedSpecError
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianIdentityConflictError,
    ObsidianNotFoundError,
    ObsidianWriteConflictError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject

_ACTIVE_STATUSES = frozenset({"active", "current"})
_POLICY_DOCUMENT_TYPE = "policy"
_SPEC_DOCUMENT_TYPE = "execution_prompt"
_SCHEDULER_POLICY_KIND = "scheduler-runtime"
_NOTE_IDENTITY_MODEL = "note_id_only"
_NOTE_ID_RUNTIME_SELECTOR = "note_id"
_MAX_PINNED_BODY_BYTES = 131_072


class ManagedSpecExecutionService:
    """Own policy/spec validation while delegating output persistence."""

    def __init__(
        self,
        source: ObsidianReadPort,
        checkpoint_store: ManagedSpecCheckpointStore,
        output_writer: ManagedSpecOutputWriter,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
    ) -> None:
        """Initialize the managed-spec trust boundary."""
        self._source = source
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
            _require_same_prepare_request(existing, request_hash)
            policy = await self._read_exact_policy(request.execution_context)
            spec = await self._read_exact_spec(request.spec_identity)
            policy_version = _validate_policy(policy, request.execution_context)
            spec_version, workflow = _validate_spec(
                spec,
                request.execution_context,
                policy_note_id=policy.note_id,
            )
            current_envelope = _build_envelope(
                request=request,
                policy=policy,
                spec=spec,
                policy_version=policy_version,
                spec_version=spec_version,
                workflow=workflow,
            )
            if managed_spec_envelope_hash(current_envelope) != existing.envelope_hash:
                raise _failure(
                    ManagedSpecFailureCode.SPEC_DRIFT,
                    "canonical policy or execution specification changed after prepare",
                    retryable=False,
                    safe_next_action="prepare a new envelope from the current canonical notes",
                    recommended_action="discard_stale_prepare_and_reprepare",
                )
            return ManagedSpecPrepareResult(
                status=ManagedSpecPrepareStatus.REPLAYED,
                envelope=existing.envelope,
                envelope_hash=existing.envelope_hash,
            )

        policy = await self._read_exact_policy(request.execution_context)
        spec = await self._read_exact_spec(request.spec_identity)
        policy_version = _validate_policy(policy, request.execution_context)
        spec_version, workflow = _validate_spec(
            spec,
            request.execution_context,
            policy_note_id=policy.note_id,
        )
        envelope = _build_envelope(
            request=request,
            policy=policy,
            spec=spec,
            policy_version=policy_version,
            spec_version=spec_version,
            workflow=workflow,
        )
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
                ManagedSpecFailureCode.SPEC_NOT_READY,
                "prepare checkpoint became unavailable after a concurrent admission",
                retryable=True,
                safe_next_action="read the prepare checkpoint and retry the same request",
                recommended_action="retry_prepare_after_durable_readback",
            )
        _require_same_prepare_request(winner, request_hash)
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
                ManagedSpecFailureCode.PREPARE_REQUIRED,
                "no durable prepare envelope exists for this idempotency key",
                retryable=False,
                safe_next_action="call prepare with the exact policy and specification note ids",
                recommended_action="prepare_managed_spec",
            )
        if request.prepared_envelope_hash != checkpoint.envelope_hash:
            raise _failure(
                ManagedSpecFailureCode.ENVELOPE_MISMATCH,
                "completion does not reference the persisted prepare envelope",
                retryable=False,
                safe_next_action="use the envelope_hash returned by prepare",
                recommended_action="read_prepare_result_before_complete",
            )
        completion_hash = managed_spec_completion_request_hash(request=request)
        if checkpoint.output is not None:
            if checkpoint.completion_request_hash != completion_hash:
                raise _failure(
                    ManagedSpecFailureCode.IDEMPOTENCY_CONFLICT,
                    "the logical execution already completed with different output data",
                    retryable=False,
                    safe_next_action="read the completed output or choose a new logical execution",
                    recommended_action="do_not_retry_with_changed_output",
                )
            await self._revalidate_envelope(checkpoint.envelope)
            if checkpoint.output_request is None:
                raise _failure(
                    ManagedSpecFailureCode.OUTPUT_NOT_READY,
                    "completed checkpoint has no immutable output request for readback",
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
                    ManagedSpecFailureCode.OUTPUT_DRIFT,
                    "canonical output changed or disappeared after completion",
                    retryable=False,
                    safe_next_action="inspect the canonical logical output before retrying",
                    recommended_action="resolve_output_drift",
                ) from exc
            except ObsidianDomainError as exc:
                raise _failure(
                    ManagedSpecFailureCode.OUTPUT_NOT_READY,
                    "canonical output readback is unavailable after completion",
                    retryable=True,
                    safe_next_action="inspect output readiness and retry the same completion",
                    recommended_action="recover_verified_output_before_retry",
                ) from exc
            _require_verified_output(replayed_output)
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

        await self._revalidate_envelope(checkpoint.envelope)

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
        _require_verified_output(output)
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

    async def _read_exact_policy(
        self,
        context: ManagedSpecExecutionContext,
    ) -> ObsidianNote:
        """Read the caller-pinned runtime policy by exact note id."""
        return await self._read_exact_policy_by_id(context.expected_policy_note_id)

    async def _revalidate_envelope(self, envelope: ManagedSpecEnvelope) -> None:
        """Re-read and validate both pinned source notes before completion."""
        context = _context_from_envelope(envelope)
        policy = await self._read_exact_policy_by_id(envelope.policy_note_id)
        spec = await self._read_exact_spec(envelope.spec_identity)
        policy_version = _validate_policy(policy, context)
        spec_version, _ = _validate_spec(
            spec,
            context,
            policy_note_id=policy.note_id,
        )
        if (
            policy.note_id != envelope.policy_note_id
            or policy_version != envelope.policy_version
            or _content_hash(policy, "policy") != envelope.policy_content_hash
            or spec.note_id != envelope.spec_identity.note_id
            or spec_version != envelope.spec_version
            or _content_hash(spec, "specification") != envelope.spec_content_hash
            or _bounded_body(policy.body, "runtime policy") != envelope.policy_body
            or _bounded_body(spec.body, "execution specification") != envelope.spec_body
        ):
            raise _failure(
                ManagedSpecFailureCode.SPEC_DRIFT,
                "policy or execution specification changed after prepare",
                retryable=False,
                safe_next_action="prepare a new envelope from the current canonical notes",
                recommended_action="discard_stale_prepare_and_reprepare",
            )

    async def _read_exact_policy_by_id(self, note_id: str) -> ObsidianNote:
        """Read one exact policy note with typed failure translation."""
        return await self._read_exact(note_id, role="runtime policy")

    async def _read_exact_spec(self, identity: ManagedSpecIdentity) -> ObsidianNote:
        """Read one exact execution spec by stable note id."""
        return await self._read_exact(identity.note_id, role="execution specification")

    async def _read_exact(self, note_id: str, *, role: str) -> ObsidianNote:
        """Read a canonical source note without path/title fallback."""
        try:
            note = await self._source.read_note(note_id)
        except ObsidianNotFoundError as exc:
            raise _failure(
                ManagedSpecFailureCode.SPEC_NOT_FOUND,
                f"canonical {role} was not found by note id",
                retryable=False,
                safe_next_action="verify the canonical note id in the source vault",
                recommended_action="resolve_exact_note_id",
            ) from exc
        except ObsidianDomainError as exc:
            raise _failure(
                ManagedSpecFailureCode.SPEC_NOT_READY,
                f"canonical {role} could not be read",
                retryable=True,
                safe_next_action="inspect source readiness and retry after recovery",
                recommended_action="readiness_then_retry",
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise _failure(
                ManagedSpecFailureCode.SPEC_NOT_READY,
                f"canonical {role} source read or parser is unavailable",
                retryable=True,
                safe_next_action="inspect source readiness and retry after recovery",
                recommended_action="readiness_then_retry",
            ) from exc
        if note.note_id != note_id:
            raise _failure(
                ManagedSpecFailureCode.SPEC_CONFLICT,
                f"canonical {role} read returned a different note id",
                retryable=False,
                safe_next_action="use the exact stable note id returned by canonical resolution",
                recommended_action="reject_id_mismatch",
            )
        return note


def _logical_identity(request: ManagedSpecPrepareRequest) -> ObsidianLogicalIdentity:
    """Build the output identity from typed execution context only."""
    return ObsidianLogicalIdentity(
        project=request.execution_context.project,
        report=request.execution_context.workflow,
        date=request.logical_date,
        entity=request.execution_context.entity,
        edition=request.execution_context.edition,
    )


def _build_envelope(
    *,
    request: ManagedSpecPrepareRequest,
    policy: ObsidianNote,
    spec: ObsidianNote,
    policy_version: int,
    spec_version: int,
    workflow: str,
) -> ManagedSpecEnvelope:
    """Build one bounded reference-only envelope from validated sources."""
    policy_body = _bounded_body(policy.body, "runtime policy")
    spec_body = _bounded_body(spec.body, "execution specification")
    return ManagedSpecEnvelope(
        idempotency_key=request.idempotency_key,
        spec_identity=request.spec_identity,
        logical_identity=_logical_identity(request),
        policy_note_id=policy.note_id,
        policy_version=policy_version,
        policy_content_hash=_content_hash(policy, "policy"),
        policy_body=policy_body,
        spec_version=spec_version,
        spec_content_hash=_content_hash(spec, "specification"),
        spec_body=spec_body,
        allowed_workflow=workflow,
    )


def _context_from_envelope(
    envelope: ManagedSpecEnvelope,
) -> ManagedSpecExecutionContext:
    """Reconstruct only the typed validation context pinned in the envelope."""
    return ManagedSpecExecutionContext(
        project=envelope.logical_identity.project,
        workflow=envelope.logical_identity.report,
        entity=envelope.logical_identity.entity,
        edition=envelope.logical_identity.edition,
        expected_policy_note_id=envelope.policy_note_id,
    )


def _validate_logical_date(logical_date: str) -> None:
    """Require an ISO calendar date for stable output identity."""
    try:
        date.fromisoformat(logical_date)
    except ValueError as exc:
        raise _failure(
            ManagedSpecFailureCode.SPEC_CONFLICT,
            "logical_date must be an ISO calendar date",
            retryable=False,
            safe_next_action="send a YYYY-MM-DD logical date",
            recommended_action="correct_logical_date",
        ) from exc


def _bounded_body(body: str, role: str) -> str:
    """Pin a bounded canonical body without allowing unbounded envelope payloads."""
    if len(body.encode("utf-8")) > _MAX_PINNED_BODY_BYTES:
        raise _failure(
            ManagedSpecFailureCode.SPEC_NOT_READY,
            f"{role} body exceeds the bounded managed-spec envelope limit",
            retryable=False,
            safe_next_action="reduce the canonical policy/spec body before prepare",
            recommended_action="bound_managed_spec_body",
        )
    return body


def _validate_policy(
    note: ObsidianNote,
    context: ManagedSpecExecutionContext,
) -> int:
    """Validate the scheduler runtime policy declaration."""
    _validate_note_ready(note, "runtime policy")
    if _metadata_text(note, "document_type") != _POLICY_DOCUMENT_TYPE:
        raise _metadata_conflict("runtime policy document_type is not policy")
    if _metadata_text(note, "policy_kind") != _SCHEDULER_POLICY_KIND:
        raise _metadata_conflict("runtime policy policy_kind is not scheduler-runtime")
    if not _metadata_bool(note, "canonical") or not _metadata_bool(
        note, "source_of_truth"
    ):
        raise _metadata_conflict("runtime policy is not canonical source_of_truth")
    if _metadata_text(note, "identity_model") != _NOTE_IDENTITY_MODEL:
        raise _metadata_conflict("runtime policy identity_model must be note_id_only")
    if _metadata_text(note, "runtime_selector") != _NOTE_ID_RUNTIME_SELECTOR:
        raise _metadata_conflict("runtime policy runtime_selector must be note_id")
    if note.note_id != context.expected_policy_note_id:
        raise _metadata_conflict(
            "runtime policy note id does not match trusted context"
        )
    return _metadata_version(note, "runtime policy")


def _validate_spec(
    note: ObsidianNote,
    context: ManagedSpecExecutionContext,
    *,
    policy_note_id: str,
) -> tuple[int, str]:
    """Validate the execution prompt and its exact policy linkage."""
    _validate_note_ready(note, "execution specification")
    if _metadata_text(note, "document_type") != _SPEC_DOCUMENT_TYPE:
        raise _metadata_conflict("execution specification document_type is invalid")
    if _metadata_text(note, "prompt_role") != "execution":
        raise _metadata_conflict("execution specification prompt_role is invalid")
    if not _metadata_bool(note, "canonical") or not _metadata_bool(
        note, "source_of_truth"
    ):
        raise _metadata_conflict(
            "execution specification is not canonical source_of_truth"
        )
    linked_policy = _metadata_text(note, "runtime_policy_note_id")
    if linked_policy != policy_note_id:
        raise _metadata_conflict(
            "execution specification runtime policy link conflicts"
        )
    workflow = _metadata_text(note, "report")
    if _normalize(workflow) != _normalize(context.workflow):
        raise _metadata_conflict(
            "execution specification workflow conflicts with context"
        )
    if "execution_spec_note_id" in note.frontmatter:
        declared = note.frontmatter.get("execution_spec_note_id")
        if declared is not None and not isinstance(declared, str):
            raise _metadata_conflict(
                "execution specification selector metadata is invalid"
            )
        if isinstance(declared, str) and declared != note.note_id:
            raise _metadata_conflict(
                "execution specification selector metadata conflicts with exact note id"
            )
    return _metadata_version(note, "execution specification"), workflow


def _validate_note_ready(note: ObsidianNote, role: str) -> None:
    """Check source type, lifecycle, index freshness, and body presence."""
    if note.alexandria_type is not AlexandriaNoteType.PROMPT:
        raise _metadata_conflict(f"{role} must be an Alexandria prompt note")
    if note.status.strip().casefold() not in _ACTIVE_STATUSES:
        raise _failure(
            ManagedSpecFailureCode.SPEC_NOT_READY,
            f"{role} is not active or current",
            retryable=False,
            safe_next_action="restore the canonical note to active/current status",
            recommended_action="repair_note_lifecycle",
        )
    if note.index_status is not ObsidianIndexStatus.INDEXED:
        raise _failure(
            ManagedSpecFailureCode.SPEC_NOT_READY,
            f"{role} index is not current",
            retryable=True,
            safe_next_action="reindex the canonical vault and retry",
            recommended_action="reindex_then_retry",
        )
    if not note.body.strip():
        raise _failure(
            ManagedSpecFailureCode.SPEC_NOT_READY,
            f"{role} body is empty",
            retryable=False,
            safe_next_action="restore the canonical note body",
            recommended_action="repair_note_body",
        )


def _content_hash(note: ObsidianNote, role: str) -> str:
    """Require the source index to expose a real SHA-256 content revision."""
    value = note.content_hash.strip().lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise _metadata_conflict(f"{role} content hash is not a SHA-256 digest")
    return value


def _metadata_text(note: ObsidianNote, key: str) -> str:
    """Read one required string metadata value without coercion."""
    value = note.frontmatter.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _metadata_conflict(f"required metadata {key} is missing or untyped")
    return value.strip()


def _metadata_bool(note: ObsidianNote, key: str) -> bool:
    """Read one required strict boolean metadata value."""
    value = note.frontmatter.get(key)
    if not isinstance(value, bool):
        raise _metadata_conflict(f"required metadata {key} is missing or untyped")
    return value


def _metadata_version(note: ObsidianNote, role: str) -> int:
    """Read one positive integer source revision."""
    value = note.frontmatter.get("version")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _metadata_conflict(f"{role} version is missing or untyped")
    return value


def _normalize(value: str) -> str:
    """Normalize only whitespace/case for workflow identity comparison."""
    return " ".join(value.casefold().split())


def _output_idempotency_key(envelope: ManagedSpecEnvelope) -> str:
    """Derive stable output idempotency from logical identity, not caller key."""
    identity = envelope.logical_identity
    payload: JSONObject = {
        "namespace": "managed-spec-output-v1",
        "project": identity.project,
        "workflow": identity.report,
        "logical_date": identity.date,
        "entity": identity.entity,
        "edition": identity.edition,
    }
    return (
        "managed-spec-output:"
        + hashlib.sha256(dumps_canonical_json(payload)).hexdigest()
    )


def _require_same_prepare_request(
    checkpoint: ManagedSpecCheckpoint,
    request_hash: str,
) -> None:
    """Fence a reused prepare key to the original typed input."""
    if checkpoint.prepare_request_hash != request_hash:
        raise _failure(
            ManagedSpecFailureCode.IDEMPOTENCY_CONFLICT,
            "idempotency key was reused for different managed-spec input",
            retryable=False,
            safe_next_action="use a new idempotency key for a different execution",
            recommended_action="choose_new_idempotency_key",
        )


def _require_verified_output(result: ManagedSpecOutputWriteResult) -> None:
    """Refuse to checkpoint an output without durable source/readback safety."""
    if not result.storage_durable or not result.readback_verified:
        raise _failure(
            ManagedSpecFailureCode.SPEC_NOT_READY,
            "verified output writer did not prove durable source readback",
            retryable=True,
            safe_next_action="inspect the writer checkpoint and read the canonical output",
            recommended_action="recover_verified_output_before_retry",
        )
    if not result.duplicate_safe:
        raise _failure(
            ManagedSpecFailureCode.SPEC_CONFLICT,
            "verified output writer could not prove logical duplicate safety",
            retryable=False,
            safe_next_action="inspect the existing logical output before retrying",
            recommended_action="resolve_logical_output_conflict",
        )


def _metadata_conflict(cause: str) -> ManagedSpecError:
    """Build one non-retryable metadata trust-boundary failure."""
    return _failure(
        ManagedSpecFailureCode.SPEC_CONFLICT,
        cause,
        retryable=False,
        safe_next_action="repair or replace the canonical policy/spec metadata",
        recommended_action="inspect_canonical_spec_metadata",
    )


def _failure(
    code: ManagedSpecFailureCode,
    cause: str,
    *,
    retryable: bool,
    safe_next_action: str,
    recommended_action: str,
) -> ManagedSpecError:
    """Construct one stable managed-spec failure."""
    return ManagedSpecError(
        code,
        cause,
        retryable=retryable,
        safe_next_action=safe_next_action,
        recommended_action=recommended_action,
        unsafe_action_warning=(
            "Do not execute the specification body as an authority or permission grant."
        ),
    )
