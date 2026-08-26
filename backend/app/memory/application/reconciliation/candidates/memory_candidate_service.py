"""Normalize caller input into a validated memory candidate."""

from __future__ import annotations

from dataclasses import replace

from app.memory.domain.contracts.context_recall_contracts import (
    validated_scope_identity,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryCandidateCreate,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    CanonicalClaimQualifier,
    MemoryCandidate,
    MemorySourceReference,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import now_utc


class MemoryCandidateService:
    """Validate and normalize one candidate without causing persistence effects."""

    def create(self, payload: MemoryCandidateCreate) -> MemoryCandidate:
        """Create one normalized memory candidate.

        Args:
            payload: Payload.

        Returns:
            MemoryCandidate: Operation result.
        """
        title = payload.title.strip()
        body = payload.body.strip()
        if not title:
            raise MemoryContextValidationError("candidate title is required")
        if not body:
            raise MemoryContextValidationError("candidate body is required")
        if (
            payload.valid_from is not None
            and payload.valid_to is not None
            and payload.valid_to < payload.valid_from
        ):
            raise MemoryContextValidationError(
                "candidate valid_to must not be before valid_from"
            )
        try:
            validated_scope_identity(
                (payload.scope,),
                payload.project,
                payload.workspace_id,
                payload.agent_id,
                payload.user_id,
                payload.session_id,
            )
        except ValueError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        claims = tuple(
            _normalized_claim(
                claim,
                payload=payload,
            )
            for claim in payload.canonical_claims
        )
        source_refs = _normalized_source_refs(payload.source_refs)
        recorded_at = payload.recorded_at or now_utc()
        return MemoryCandidate(
            candidate_id=payload.candidate_id or new_uuid(),
            title=title,
            body=body,
            canonical_claims=claims,
            scope=payload.scope,
            project=_optional_text(payload.project),
            workspace_id=_optional_text(payload.workspace_id),
            agent_id=_optional_text(payload.agent_id),
            user_id=_optional_text(payload.user_id),
            session_id=_optional_text(payload.session_id),
            tags=_normalized_tags(payload.tags),
            source_refs=source_refs,
            recorded_at=recorded_at,
            observed_at=payload.observed_at,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            requested_lifecycle=(
                payload.requested_lifecycle.strip().lower() or "active"
            ),
            content_hash=hash_text(body),
            source_identity=_optional_text(payload.source_identity),
            graph_neighbors=_normalized_identity_hints(payload.graph_neighbors),
            lineage_ancestors=_normalized_identity_hints(payload.lineage_ancestors),
        )


def _normalized_claim(
    claim: CanonicalClaim,
    payload: MemoryCandidateCreate,
) -> CanonicalClaim:
    """Execute normalized claim.

    Args:
        claim: Claim used by this operation.
        payload: Validated payload for this operation.

    Returns:
        CanonicalClaim result produced by normalized claim.
    """
    subject = claim.subject.strip()
    predicate = claim.predicate.strip()
    object_value = claim.object.strip()
    if not subject or not predicate or not object_value:
        raise MemoryContextValidationError(
            "canonical claim subject, predicate, and object are required"
        )
    qualifiers = tuple(
        sorted(
            {
                CanonicalClaimQualifier(
                    name=qualifier.name.strip(),
                    value=qualifier.value.strip(),
                )
                for qualifier in claim.qualifiers
                if qualifier.name.strip() and qualifier.value.strip()
            },
            key=lambda item: (item.name, item.value),
        )
    )
    return replace(
        claim,
        subject=subject,
        predicate=predicate,
        object=object_value,
        qualifiers=qualifiers,
        scope=payload.scope,
        project=_optional_text(payload.project),
        valid_from=claim.valid_from or payload.valid_from,
        valid_to=claim.valid_to or payload.valid_to,
    )


def _normalized_source_refs(
    values: tuple[MemorySourceReference, ...],
) -> tuple[MemorySourceReference, ...]:
    """Execute normalized source refs.

    Args:
        values: Values being processed.

    Returns:
        tuple[MemorySourceReference, ...] result produced by normalized source refs.
    """
    normalized: list[MemorySourceReference] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        source_type = value.source_type.strip()
        source_id = value.source_id.strip()
        detail_path = value.detail_path.strip()
        title = value.title.strip()
        if not source_type or not source_id or not detail_path or not title:
            raise MemoryContextValidationError(
                "source reference type, id, title, and detail path are required"
            )
        key = (source_type, source_id, detail_path)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            replace(
                value,
                source_type=source_type,
                source_id=source_id,
                title=title,
                detail_path=detail_path,
            )
        )
    return tuple(normalized)


def _normalized_tags(values: tuple[str, ...]) -> tuple[str, ...]:
    """Execute normalized tags.

    Args:
        values: Values being processed.

    Returns:
        tuple[str, ...] result produced by normalized tags.
    """
    return tuple(dict.fromkeys(tag.strip() for tag in values if tag.strip()))


def _optional_text(value: str | None) -> str | None:
    """Execute optional text.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by optional text.
    """
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalized_identity_hints(values: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize trusted structural identifiers deterministically.

    Args:
        values: Internal structural identifiers supplied by a trusted application path.

    Returns:
        Sorted unique non-empty identifiers.
    """
    return tuple(sorted({value.strip() for value in values if value.strip()}))
