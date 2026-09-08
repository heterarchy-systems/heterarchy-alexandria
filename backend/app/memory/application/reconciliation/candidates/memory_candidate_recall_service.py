"""Build reconciliation-specific recall candidates from Context search matches."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from app.memory.domain.entities.context_read_models import (
    ContextGraphEvidence,
    ContextRecord,
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
from app.shared.compute.native_text_hashing import hash_text
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONValue

_CLAIMS_ADAPTER = TypeAdapter(tuple[CanonicalClaim, ...])


class MemoryCandidateRecallService:
    """Recall and normalize existing Contexts for relation classification."""

    def __init__(
        self,
        recall_source: IMemoryCandidateRecallSource,
        repository: IMemoryReconciliationTemporalRepository,
    ) -> None:
        """Initialize MemoryCandidateRecallService state and dependencies.

        Args:
            recall_source: Recall source used by this operation.
            repository: Repository used by this operation.
        """
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
            if not _matches_candidate_identity(match.context, candidate):
                continue
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


def _matches_candidate_identity(
    context: ContextRecord,
    candidate: MemoryCandidate,
) -> bool:
    """Return whether a recalled Context belongs to the proposal's identity boundary.

    This is defense-in-depth behind the scoped Context search adapter. It prevents
    cross-project or cross-owner memory from reaching reconciliation semantics if an
    upstream adapter, test double, or future retrieval lane returns an invalid match.

    Args:
        context: Recalled Context read model.
        candidate: Memory proposal owning the reconciliation scope identity.

    Returns:
        Whether the Context is compatible with the proposal's exact recall identity.
    """
    if context.scope is not candidate.scope:
        return False
    identities = (
        (candidate.project, context.project),
        (candidate.workspace_id, context.workspace_id),
        (candidate.agent_id, context.agent_id),
        (candidate.user_id, context.user_id),
        (candidate.session_id, context.session_id),
    )
    return all(
        expected is None or actual == expected for expected, actual in identities
    )


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
    content_hash = _metadata_text(metadata, "content_hash") or hash_text(
        context.content
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
        graph_neighbors=_graph_neighbors(context.id, match.graph_evidence),
        lineage_ancestors=(
            () if temporal is None else tuple(sorted(set(temporal.supersedes)))
        ),
    )


def _graph_neighbors(
    context_id: str, evidence: tuple[ContextGraphEvidence, ...]
) -> tuple[str, ...]:
    """Return deterministic counterpart Context ids from trusted graph evidence.

    Args:
        context_id: Recalled Context owning the graph evidence.
        evidence: Score-preserving graph evidence attached by the graph lane.

    Returns:
        Sorted unique neighboring Context identifiers.
    """
    neighbors: set[str] = set()
    for item in evidence:
        if item.source_context_id == context_id:
            neighbors.add(item.target_context_id)
        elif item.target_context_id == context_id:
            neighbors.add(item.source_context_id)
    neighbors.discard(context_id)
    return tuple(sorted(neighbors))


def _candidate_query(candidate: MemoryCandidate) -> str:
    """Execute candidate query.

    Args:
        candidate: Candidate used by this operation.

    Returns:
        str result produced by candidate query.
    """
    if candidate.canonical_claims:
        return " ".join(
            f"{claim.subject} {claim.predicate} {claim.object}"
            for claim in candidate.canonical_claims
        )
    return f"{candidate.title} {candidate.body[:1000]}"


def _canonical_claims(metadata: ContextMetadataPayload) -> tuple[CanonicalClaim, ...]:
    """Execute canonical claims.

    Args:
        metadata: Metadata used by this operation.

    Returns:
        tuple[CanonicalClaim, ...] result produced by canonical claims.
    """
    value = metadata.get("canonical_claims")
    if isinstance(value, str):
        try:
            value = loads_json(value)
        except (TypeError, ValueError):
            return ()
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
    """Execute metadata text.

    Args:
        metadata: Metadata used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by metadata text.
    """
    value: JSONValue | None = metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
