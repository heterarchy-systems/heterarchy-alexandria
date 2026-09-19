"""Draft validation, sealing hashes, and lineage revision selection.

These helpers are pure: they observe no clock, filesystem, or store, so the
seal identity is reproducible and unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import cast

from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageAttributedItem,
    ResumePackageDraft,
    ResumePackageEvidenceRef,
    ResumePackageLineage,
    ResumePackageLineageEntry,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryResumePackageValidationError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import aware_utc_datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedResumePackage:
    """Normalized draft plus resolved evidence used for sealing."""

    draft: ResumePackageDraft
    evidence_refs: tuple[ResumePackageEvidenceRef, ...]
    draft_hash: str


def validated_resume_package(
    draft: ResumePackageDraft,
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
) -> ValidatedResumePackage:
    """Validate one draft against its resolved evidence and seal the hash.

    Args:
        draft: Caller-supplied resume package draft.
        evidence_refs: Evidence references resolved from stored Contexts.

    Returns:
        Normalized draft, evidence, and the stable draft hash.

    Raises:
        MemoryResumePackageValidationError: When any contract invariant is
            violated.
    """
    normalized_draft = _validated_draft(draft)
    _validated_evidence(evidence_refs, normalized_draft)
    return ValidatedResumePackage(
        draft=normalized_draft,
        evidence_refs=evidence_refs,
        draft_hash=resume_package_draft_hash(normalized_draft, evidence_refs),
    )


def resume_package_draft_hash(
    draft: ResumePackageDraft,
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
) -> str:
    """Compute the stable content hash over one draft and its evidence.

    The hash covers caller-supplied content and the server-observed evidence
    (including content hashes), so a retry matches only when both the request
    and the observed evidence are unchanged.

    Args:
        draft: Normalized resume package draft.
        evidence_refs: Evidence references resolved from stored Contexts.

    Returns:
        Lowercase SHA-256 hex digest over the canonical JSON payload.
    """
    payload: JSONValue = {
        "project": draft.project,
        "goal": draft.goal,
        "summary": draft.summary,
        "current_state": draft.current_state,
        "next_single_action": draft.next_single_action,
        "covered_from": _isoformat(draft.covered_from),
        "covered_to": _isoformat(draft.covered_to),
        "lineage": _lineage_payload(draft.lineage),
        "evidence_refs": _evidence_payload(evidence_refs),
        "accepted_changes": _items_payload(draft.accepted_changes),
        "constraints": _items_payload(draft.constraints),
        "verified_complete": list(draft.verified_complete),
        "implemented_unverified": list(draft.implemented_unverified),
        "unfinished_tasks": list(draft.unfinished_tasks),
        "uncertain_results": list(draft.uncertain_results),
        "blockers": list(draft.blockers),
    }
    return sha256(dumps_canonical_json(payload)).hexdigest()


def next_lineage_successor(
    entries: tuple[ResumePackageLineageEntry, ...],
) -> tuple[int, str | None]:
    """Return the next revision and predecessor for one lineage.

    Args:
        entries: Stored packages already observed in the lineage.

    Returns:
        Tuple of the next monotonic revision and the predecessor package id
        (the highest-revision stored package), or ``(1, None)`` for a fresh
        lineage.
    """
    if not entries:
        return 1, None
    predecessor = max(entries, key=lambda entry: entry.package_revision)
    return predecessor.package_revision + 1, predecessor.package_id


def _validated_draft(draft: ResumePackageDraft) -> ResumePackageDraft:
    """Normalize and validate one caller draft.

    Args:
        draft: Caller-supplied resume package draft.

    Returns:
        Normalized immutable draft.

    Raises:
        MemoryResumePackageValidationError: When any field violates the
            single-line, non-blank, or ordering invariants.
    """
    lineage = draft.lineage
    if lineage.previous_package_id is not None or lineage.package_revision is not None:
        raise MemoryResumePackageValidationError(
            "Resume package lineage seal fields must be left unset on draft input"
        )
    covered_from = _aware(draft.covered_from, "covered_from")
    covered_to = _aware(draft.covered_to, "covered_to")
    if covered_to < covered_from:
        raise MemoryResumePackageValidationError(
            "covered_to must be after covered_from"
        )
    return ResumePackageDraft(
        project=_optional_line("project", draft.project),
        goal=_required_line("goal", draft.goal),
        summary=_required_line("summary", draft.summary),
        current_state=_required_line("current_state", draft.current_state),
        next_single_action=_required_line(
            "next_single_action", draft.next_single_action
        ),
        covered_from=covered_from,
        covered_to=covered_to,
        lineage=ResumePackageLineage(
            lineage_id=_required_line("lineage.lineage_id", lineage.lineage_id),
            worker_id=_optional_line("lineage.worker_id", lineage.worker_id),
            run_id=_optional_line("lineage.run_id", lineage.run_id),
            workspace_id=_optional_line("lineage.workspace_id", lineage.workspace_id),
            session_id=_optional_line("lineage.session_id", lineage.session_id),
        ),
        evidence_context_ids=_validated_evidence_ids(draft.evidence_context_ids),
        accepted_changes=_validated_items(draft.accepted_changes),
        constraints=_validated_items(draft.constraints),
        verified_complete=_validated_lines(
            "verified_complete", draft.verified_complete
        ),
        implemented_unverified=_validated_lines(
            "implemented_unverified", draft.implemented_unverified
        ),
        unfinished_tasks=_validated_lines("unfinished_tasks", draft.unfinished_tasks),
        uncertain_results=_validated_lines(
            "uncertain_results", draft.uncertain_results
        ),
        blockers=_validated_lines("blockers", draft.blockers),
        request_id=_optional_line("request_id", draft.request_id),
    )


def _validated_evidence(
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
    draft: ResumePackageDraft,
) -> None:
    """Check resolved evidence against the draft contract.

    Args:
        evidence_refs: Evidence references resolved from stored Contexts.
        draft: Normalized resume package draft.

    Raises:
        MemoryResumePackageValidationError: When evidence is empty, does not
            match the requested ids, or an attributed item points outside the
            sealed evidence set.
    """
    if not evidence_refs:
        raise MemoryResumePackageValidationError(
            "Resume package requires at least one stored evidence context"
        )
    evidence_ids = {evidence_ref.context_id for evidence_ref in evidence_refs}
    if evidence_ids != set(draft.evidence_context_ids):
        raise MemoryResumePackageValidationError(
            "Resolved evidence set does not match the requested evidence ids"
        )
    for item in (*draft.accepted_changes, *draft.constraints):
        if item.source_context_id not in evidence_ids:
            raise MemoryResumePackageValidationError(
                "Resume package attribution references unsealed evidence: "
                f"{item.source_context_id}"
            )


def _validated_evidence_ids(
    evidence_context_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Normalize evidence context ids, dropping exact duplicates.

    Args:
        evidence_context_ids: Caller-supplied stored Context identifiers.

    Returns:
        Deduplicated identifiers in first-occurrence order.

    Raises:
        MemoryResumePackageValidationError: When any identifier is blank or
            the list is empty.
    """
    deduplicated: list[str] = []
    seen: set[str] = set()
    for context_id in evidence_context_ids:
        normalized = _required_line("evidence_context_ids", context_id)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(normalized)
    if not deduplicated:
        raise MemoryResumePackageValidationError(
            "Resume package requires at least one stored evidence context"
        )
    return tuple(deduplicated)


def _validated_items(
    items: tuple[ResumePackageAttributedItem, ...],
) -> tuple[ResumePackageAttributedItem, ...]:
    """Normalize attributed items.

    Args:
        items: Caller-supplied attributed items.

    Returns:
        Normalized attributed items.

    Raises:
        MemoryResumePackageValidationError: When item text or attribution is
            blank or multi-line.
    """
    return tuple(
        ResumePackageAttributedItem(
            text=_required_line("attributed item text", item.text),
            source_context_id=_required_line(
                "attributed item source_context_id", item.source_context_id
            ),
        )
        for item in items
    )


def _validated_lines(
    field: str,
    values: tuple[str, ...],
) -> tuple[str, ...]:
    """Normalize a list of single-line values.

    Args:
        field: Field name used in error messages.
        values: Caller-supplied values.

    Returns:
        Normalized values.

    Raises:
        MemoryResumePackageValidationError: When any value is blank or
            multi-line.
    """
    return tuple(_required_line(field, value) for value in values)


def _required_line(field: str, value: str) -> str:
    """Validate one required single-line value.

    Args:
        field: Field name used in error messages.
        value: Caller-supplied value.

    Returns:
        Stripped single-line value.

    Raises:
        MemoryResumePackageValidationError: When the value is blank or
            multi-line.
    """
    normalized = value.strip()
    if not normalized or "\n" in normalized:
        raise MemoryResumePackageValidationError(
            f"Resume package field must be a non-blank single line: {field}"
        )
    return normalized


def _optional_line(field: str, value: str | None) -> str | None:
    """Validate one optional single-line value.

    Args:
        field: Field name used in error messages.
        value: Caller-supplied value or None.

    Returns:
        Stripped single-line value or None.

    Raises:
        MemoryResumePackageValidationError: When the value is blank or
            multi-line.
    """
    if value is None:
        return None
    return _required_line(field, value)


def _lineage_payload(lineage: ResumePackageLineage) -> JSONValue:
    """Build the canonical lineage payload for hashing.

    Args:
        lineage: Normalized draft lineage.

    Returns:
        JSON-compatible lineage payload.
    """
    return {
        "lineage_id": lineage.lineage_id,
        "worker_id": lineage.worker_id,
        "run_id": lineage.run_id,
        "workspace_id": lineage.workspace_id,
        "session_id": lineage.session_id,
    }


def _evidence_payload(
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
) -> JSONValue:
    """Build the canonical order-independent evidence payload for hashing.

    Args:
        evidence_refs: Evidence references resolved from stored Contexts.

    Returns:
        JSON-compatible evidence payload sorted by context id.
    """
    return cast(
        JSONValue,
        [
            {
                "context_id": evidence_ref.context_id,
                "content_hash": evidence_ref.content_hash,
                "source": evidence_ref.source,
                "created_at": _isoformat(evidence_ref.created_at),
                "observed_updated_at": _isoformat(evidence_ref.observed_updated_at),
            }
            for evidence_ref in sorted(
                evidence_refs,
                key=lambda item: item.context_id,
            )
        ],
    )


def _items_payload(
    items: tuple[ResumePackageAttributedItem, ...],
) -> JSONValue:
    """Build the canonical attributed-item payload for hashing.

    Args:
        items: Normalized attributed items.

    Returns:
        JSON-compatible item payload.
    """
    return cast(
        JSONValue,
        [
            {"text": item.text, "source_context_id": item.source_context_id}
            for item in items
        ],
    )


def _aware(value: datetime, field: str) -> datetime:
    """Validate and normalize one timezone-aware datetime field.

    Args:
        value: Caller-supplied datetime.
        field: Field name used in error messages.

    Returns:
        Normalized aware UTC datetime.

    Raises:
        MemoryResumePackageValidationError: When the datetime is naive.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryResumePackageValidationError(
            f"Resume package field must be timezone-aware: {field}"
        )
    return aware_utc_datetime(value)


def _isoformat(value: datetime) -> str:
    """Format one datetime in canonical UTC ISO-8601 form.

    Args:
        value: Aware datetime value.

    Returns:
        Canonical ISO-8601 text.
    """
    return aware_utc_datetime(value).isoformat()
