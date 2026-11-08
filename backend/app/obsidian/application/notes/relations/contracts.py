"""Normalization, replay identity, and issue contracts for note relations."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from typing_extensions import TypedDict

from app.obsidian.application.notes.relations.relation_enums import (
    RelationIssueCapability,
    RelationIssueCode,
)
from app.obsidian.domain.contracts.obsidian_relation_contracts import (
    ObsidianRelateRequest,
)
from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateIssue
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianRelationType
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
    ObsidianWriteConflictError,
)
from app.shared.exceptions.obsidian_relation_exceptions import (
    ObsidianRelateInvalidRelationError,
    ObsidianRelateSelfEdgeError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONValue


class RelationRequestHashPayload(TypedDict, closed=True):
    """Exact closed JSON shape used to fence relation request replays."""

    source_note_id: str
    target_note_id: str
    relation: str
    expected_source_hash: str | None


class RelationReferencePayload(TypedDict, closed=True):
    """Exact closed frontmatter record for one directed note relation."""

    id: str
    path: str
    relation: str


def normalize_request(request: ObsidianRelateRequest) -> ObsidianRelateRequest:
    """Normalize request identifiers and validate an optional source CAS hash.

    Args:
        request: Caller-provided relation intent.

    Returns:
        Canonicalized relation request.
    """
    expected = request.expected_source_hash
    if expected is not None:
        expected = expected.strip().lower()
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise ObsidianValidationError(
                "expected_source_hash must be a SHA-256 hexadecimal digest"
            )
    return replace(
        request,
        source_note_id=request.source_note_id.strip(),
        target_note_id=request.target_note_id.strip(),
        idempotency_key=request.idempotency_key.strip(),
        expected_source_hash=expected,
    )


def validate_request(request: ObsidianRelateRequest) -> None:
    """Reject unsupported relation intent before any read or write.

    Args:
        request: Normalized relation intent.
    """
    if request.source_note_id == request.target_note_id:
        raise ObsidianRelateSelfEdgeError(request.source_note_id)
    if request.relation is ObsidianRelationType.WIKILINK:
        raise ObsidianRelateInvalidRelationError(request.relation.value)


def validate_source_hash(request: ObsidianRelateRequest, actual: str) -> None:
    """Apply the caller's explicit source compare-and-swap token.

    Args:
        request: Normalized relation intent.
        actual: Current canonical source content hash.
    """
    if (
        request.expected_source_hash is not None
        and actual != request.expected_source_hash
    ):
        raise ObsidianWriteConflictError(
            "OBSIDIAN_WRITE_CONFLICT: expected source content hash does not match "
            "the current note"
        )


def relate_request_hash(request: ObsidianRelateRequest) -> str:
    """Return a deterministic immutable intent hash for replay fencing.

    Args:
        request: Normalized relation intent.

    Returns:
        Canonical SHA-256 digest of the four persisted identity fields.
    """
    typed_payload = RelationRequestHashPayload(
        source_note_id=request.source_note_id,
        target_note_id=request.target_note_id,
        relation=request.relation.value,
        expected_source_hash=request.expected_source_hash,
    )
    payload: dict[str, JSONValue] = dict[str, JSONValue](typed_payload)
    return hashlib.sha256(dumps_canonical_json(payload)).hexdigest()


def issue(
    *,
    code: RelationIssueCode,
    cause: str,
    affected_capability: RelationIssueCapability,
    retryable: bool,
    safe_next_action: str,
    recovery_run_id: str | None = None,
) -> ObsidianRelateIssue:
    """Build one bounded actionable relation issue.

    Args:
        code: Stable relation issue identifier.
        cause: Secret-safe explanation of the observed failure.
        affected_capability: Relation capability affected by the issue.
        retryable: Whether the caller can safely retry with the same key.
        safe_next_action: Recommended bounded recovery action.
        recovery_run_id: Relevant graph recovery run, when known.

    Returns:
        Typed issue evidence with the established wire strings.
    """
    return ObsidianRelateIssue(
        code=code.value,
        cause=cause,
        affected_capability=affected_capability.value,
        retryable=retryable,
        safe_next_action=safe_next_action,
        recovery_run_id=recovery_run_id,
    )
