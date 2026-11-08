"""Pure values used while pinning managed-spec source revisions."""

from __future__ import annotations

from app.obsidian.application.service.managed_spec.managed_spec_failures import (
    _failure,
    _metadata_conflict,
)
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecEnvelope,
    ManagedSpecExecutionContext,
    ManagedSpecPrepareRequest,
)
from app.obsidian.domain.contracts.obsidian_logical_identity import (
    ObsidianLogicalIdentity,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecFailureCode,
)

_MAX_PINNED_BODY_BYTES = 131_072


def _logical_identity(request: ManagedSpecPrepareRequest) -> ObsidianLogicalIdentity:
    """Build the output identity from typed execution context only."""
    return ObsidianLogicalIdentity(
        project=request.execution_context.project,
        report=request.execution_context.workflow,
        date=request.logical_date,
        entity=request.execution_context.entity,
        edition=request.execution_context.edition,
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


def _bounded_body(body: str, role: str) -> str:
    """Pin a bounded canonical body without allowing unbounded envelope payloads."""
    if len(body.encode("utf-8")) > _MAX_PINNED_BODY_BYTES:
        raise _failure(
            code=ManagedSpecFailureCode.SPEC_NOT_READY,
            cause=f"{role} body exceeds the bounded managed-spec envelope limit",
            retryable=False,
            safe_next_action="reduce the canonical policy/spec body before prepare",
            recommended_action="bound_managed_spec_body",
        )
    return body


def _content_hash(note: ObsidianNote, role: str) -> str:
    """Require the source index to expose a real SHA-256 content revision."""
    value = note.content_hash.strip().lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise _metadata_conflict(cause=f"{role} content hash is not a SHA-256 digest")
    return value


def _normalize_workflow(value: str) -> str:
    """Normalize only whitespace/case for workflow identity comparison."""
    return " ".join(value.casefold().split())
