"""Exact source reads and revision pinning for managed-spec execution."""

from __future__ import annotations

from app.obsidian.application.service.managed_spec.managed_spec_failures import (
    _failure,
)
from app.obsidian.application.service.managed_spec.managed_spec_metadata import (
    ManagedSpecMetadataValidator,
)
from app.obsidian.application.service.managed_spec.managed_spec_source_values import (
    _bounded_body,
    _content_hash,
    _context_from_envelope,
    _logical_identity,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianReadPort
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecEnvelope,
    ManagedSpecPrepareRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecFailureCode,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianNotFoundError,
)


class ManagedSpecSourceVerifier:
    """Read, validate, and pin canonical policy/spec source revisions."""

    def __init__(self, source: ObsidianReadPort) -> None:
        """Initialize exact reads and the stateless note metadata validator."""
        self._source = source
        self._metadata_validator = ManagedSpecMetadataValidator()

    async def prepare_envelope(
        self,
        request: ManagedSpecPrepareRequest,
    ) -> ManagedSpecEnvelope:
        """Read policy then spec, validate both, and pin their source revisions."""
        policy = await self._read_exact(
            note_id=request.execution_context.expected_policy_note_id,
            role="runtime policy",
        )
        spec = await self._read_exact(
            note_id=request.spec_identity.note_id,
            role="execution specification",
        )
        policy_version = self._metadata_validator.validate_policy(
            note=policy,
            context=request.execution_context,
        )
        spec_version, workflow = self._metadata_validator.validate_spec(
            note=spec,
            context=request.execution_context,
            policy_note_id=policy.note_id,
        )
        return self._build_envelope(
            request=request,
            policy=policy,
            spec=spec,
            policy_version=policy_version,
            spec_version=spec_version,
            workflow=workflow,
        )

    async def revalidate(self, envelope: ManagedSpecEnvelope) -> None:
        """Re-read and compare both canonical source notes with the envelope."""
        context = _context_from_envelope(envelope=envelope)
        policy = await self._read_exact(
            note_id=envelope.policy_note_id,
            role="runtime policy",
        )
        spec = await self._read_exact(
            note_id=envelope.spec_identity.note_id,
            role="execution specification",
        )
        policy_version = self._metadata_validator.validate_policy(
            note=policy,
            context=context,
        )
        spec_version, _ = self._metadata_validator.validate_spec(
            note=spec,
            context=context,
            policy_note_id=policy.note_id,
        )
        if (
            policy.note_id != envelope.policy_note_id
            or policy_version != envelope.policy_version
            or _content_hash(note=policy, role="policy") != envelope.policy_content_hash
            or spec.note_id != envelope.spec_identity.note_id
            or spec_version != envelope.spec_version
            or _content_hash(note=spec, role="specification")
            != envelope.spec_content_hash
            or _bounded_body(body=policy.body, role="runtime policy")
            != envelope.policy_body
            or _bounded_body(body=spec.body, role="execution specification")
            != envelope.spec_body
        ):
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_DRIFT,
                cause="policy or execution specification changed after prepare",
                retryable=False,
                safe_next_action="prepare a new envelope from the current canonical notes",
                recommended_action="discard_stale_prepare_and_reprepare",
            )

    async def _read_exact(self, note_id: str, role: str) -> ObsidianNote:
        """Read one canonical source note without path/title fallback."""
        try:
            note = await self._source.read_note(note_id)
        except ObsidianNotFoundError as exc:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_FOUND,
                cause=f"canonical {role} was not found by note id",
                retryable=False,
                safe_next_action="verify the canonical note id in the source vault",
                recommended_action="resolve_exact_note_id",
            ) from exc
        except ObsidianDomainError as exc:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_READY,
                cause=f"canonical {role} could not be read",
                retryable=True,
                safe_next_action="inspect source readiness and retry after recovery",
                recommended_action="readiness_then_retry",
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_READY,
                cause=f"canonical {role} source read or parser is unavailable",
                retryable=True,
                safe_next_action="inspect source readiness and retry after recovery",
                recommended_action="readiness_then_retry",
            ) from exc
        if note.note_id != note_id:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_CONFLICT,
                cause=f"canonical {role} read returned a different note id",
                retryable=False,
                safe_next_action="use the exact stable note id returned by canonical resolution",
                recommended_action="reject_id_mismatch",
            )
        return note

    def _build_envelope(
        self,
        request: ManagedSpecPrepareRequest,
        policy: ObsidianNote,
        spec: ObsidianNote,
        policy_version: int,
        spec_version: int,
        workflow: str,
    ) -> ManagedSpecEnvelope:
        """Build one bounded reference-only envelope from validated sources."""
        policy_body = _bounded_body(body=policy.body, role="runtime policy")
        spec_body = _bounded_body(body=spec.body, role="execution specification")
        return ManagedSpecEnvelope(
            idempotency_key=request.idempotency_key,
            spec_identity=request.spec_identity,
            logical_identity=_logical_identity(request=request),
            policy_note_id=policy.note_id,
            policy_version=policy_version,
            policy_content_hash=_content_hash(note=policy, role="policy"),
            policy_body=policy_body,
            spec_version=spec_version,
            spec_content_hash=_content_hash(note=spec, role="specification"),
            spec_body=spec_body,
            allowed_workflow=workflow,
        )
