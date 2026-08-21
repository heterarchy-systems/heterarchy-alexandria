"""Build reconciliation-specific recall candidates from Context search matches."""

from __future__ import annotations

import hashlib

from app.memory.domain.entities.context_read_models import (
    ContextSearchMatch,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemoryRecallCandidate,
    MemorySourceReference,
    MemoryTemporalState,
)
from app.memory.domain.repositories.contexts.memory_candidate_recall_source import (
    IMemoryCandidateRecallSource,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_temporal_repository import (
    IMemoryReconciliationTemporalRepository,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.types.extra_types import JSONValue
from pydantic import TypeAdapter, ValidationError

_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])


class MemoryCandidateRecallService:
    """Recall and normalize existing Contexts for relation classification."""

    def __init__(
        self,
        recall_source: IMemoryCandidateRecallSource,
        repository: IMemoryReconciliationTemporalRepository,
    ) -> None:
        self._recall_source = recall_source
        self._repository = repository

    async def recall(
        self,
        candidate: MemoryCandidate,
        limit: int = 20,
    ) -> tuple[MemoryRecallCandidate, ...]:
        """Return deduplicated existing Context candidates in retrieval order.

        Args:
            candidate: Candidate.
            limit: Limit.

        Returns:
            tuple[MemoryRecallCandidate, ...]: Operation result.
        """
        pack = await self._recall_source.recall(
            candidate=candidate,
            query=_candidate_query(candidate),
            limit=limit,
        )
        recalled: list[MemoryRecallCandidate] = []
        seen_context_ids: set[str] = set()
        for match in pack.matches:
            context_id = match.context.id
            if context_id in seen_context_ids:
                continue
            seen_context_ids.add(context_id)
            temporal = await self._repository.get_temporal_state(context_id)
            recalled.append(
                recall_candidate_from_match(
                    match,
                    temporal_state=temporal,
                    candidate_hash=candidate.content_hash,
                )
            )
        return tuple(recalled)


def recall_candidate_from_match(
    match: ContextSearchMatch,
    temporal_state: MemoryTemporalState | None,
    candidate_hash: str,
) -> MemoryRecallCandidate:
    """Map one Context search match into a reconciliation recall candidate.

    Args:
        match: Match.
        temporal_state: Temporal state.
        candidate_hash: Candidate hash.

    Returns:
        MemoryRecallCandidate: Operation result.
    """
    temporal = temporal_state
    context = match.context
    metadata = context.context_metadata
    content_hash = (
        _metadata_text(metadata, "content_hash")
        or hashlib.sha256(context.content.encode("utf-8")).hexdigest()
    )
    reasons = [match.why_retrieved]
    if content_hash == candidate_hash:
        reasons.append("exact_content_hash")
    claims = _canonical_claims(metadata)
    if not claims:
        reasons.append("canonical_claims_unavailable")
    detail_path = _metadata_text(metadata, "relative_path") or f"context:{context.id}"
    source_ref = MemorySourceReference(
        source_type=context.source_type.value,
        source_id=context.id,
        title=context.title,
        detail_path=detail_path,
        source_hash=content_hash,
        observed_at=None if temporal is None else temporal.observed_at,
    )
    return MemoryRecallCandidate(
        context_id=context.id,
        title=context.title,
        body=context.content,
        canonical_claims=claims,
        scope=context.scope,
        project=context.project,
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        user_id=context.user_id,
        session_id=context.session_id,
        source_identity=_metadata_text(metadata, "source"),
        content_hash=content_hash,
        recorded_at=context.created_at if temporal is None else temporal.recorded_at,
        observed_at=None if temporal is None else temporal.observed_at,
        valid_from=None if temporal is None else temporal.valid_from,
        valid_to=None if temporal is None else temporal.valid_to,
        source_refs=(source_ref,),
        recall_reasons=tuple(reasons),
    )


def _candidate_query(candidate: MemoryCandidate) -> str:
    if candidate.canonical_claims:
        return " ".join(
            f"{claim.subject} {claim.predicate} {claim.object}"
            for claim in candidate.canonical_claims
        )
    return f"{candidate.title} {candidate.body[:1000]}"


def _canonical_claims(metadata: ContextMetadataPayload) -> tuple[CanonicalClaim, ...]:
    value = metadata.get("canonical_claims")
    if not isinstance(value, list):
        return ()
    try:
        return _CLAIMS_ADAPTER.validate_python(value)
    except ValidationError:
        return ()


def _metadata_text(
    metadata: ContextMetadataPayload,
    key: str,
) -> str | None:
    value: JSONValue | None = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
