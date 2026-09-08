"""Pure policy helpers for bounded high-level recall."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.domain.contracts.context_recall_contracts import (
    ScopeIdentity,
    validated_scope_identity,
)
from app.memory.domain.contracts.recall_contracts import RecallRequest
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.entities.recall import RecallMatch, RecallStageTrace
from app.memory.domain.event_enum.context_enums import (
    ContextRecallLifecycleStatus,
    ContextScope,
    ContextStorageStatus,
    RagStrategy,
)
from app.memory.domain.event_enum.recall_enums import (
    RecallProjectAffinity,
    RecallScopeMode,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.types.extra_types import JSONValue

MAX_RELATED_PROJECTS = 4
CONFIDENCE_THRESHOLD = 0.5


def validated_request(request: RecallRequest) -> RecallRequest:
    """Validate internal limits and normalize identity strings once."""
    query = request.query.strip()
    if not query:
        raise MemoryContextValidationError("recall query is required")
    if request.limit < 1 or request.limit > 50:
        raise MemoryContextValidationError("recall limit must be between 1 and 50")
    related = tuple(
        dict.fromkeys(item.strip() for item in request.related_projects if item.strip())
    )
    if len(related) > MAX_RELATED_PROJECTS:
        raise MemoryContextValidationError(
            "related_projects must contain at most 4 projects"
        )
    identities = {
        "project": normalize_identity(request.project),
        "workspace_id": normalize_identity(request.workspace_id),
        "agent_id": normalize_identity(request.agent_id),
        "session_id": normalize_identity(request.session_id),
        "user_id": normalize_identity(request.user_id),
    }
    return RecallRequest(
        query=query,
        limit=request.limit,
        scope_mode=request.scope_mode,
        include_scopes=tuple(dict.fromkeys(request.include_scopes)),
        project=identities["project"],
        workspace_id=identities["workspace_id"],
        agent_id=identities["agent_id"],
        session_id=identities["session_id"],
        user_id=identities["user_id"],
        related_projects=related,
        selector=request.selector,
        as_of=request.as_of,
        kind=request.kind,
        include_lifecycle_statuses=tuple(
            dict.fromkeys(request.include_lifecycle_statuses)
        ),
    )


def resolve_scope_identity(
    request: RecallRequest,
) -> tuple[ScopeIdentity, tuple[ContextScope, ...], tuple[str, ...]]:
    """Resolve AUTO lanes or validate STRICT lanes through existing authority."""
    if request.scope_mode is RecallScopeMode.STRICT:
        scopes = request.include_scopes or (ContextScope.GLOBAL,)
        try:
            identity = validated_scope_identity(
                scopes,
                request.project,
                request.workspace_id,
                request.agent_id,
                request.user_id,
                request.session_id,
            )
        except ValueError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        return identity, scopes, ()

    requested = request.include_scopes or (
        ContextScope.PROJECT,
        ContextScope.AGENT,
        ContextScope.SESSION,
        ContextScope.USER,
        ContextScope.GLOBAL,
    )
    identities = {
        ContextScope.PROJECT: request.project,
        ContextScope.AGENT: request.agent_id,
        ContextScope.SESSION: request.session_id,
        ContextScope.USER: request.user_id,
    }
    available: list[ContextScope] = []
    skipped: list[str] = []
    for scope in requested:
        identity = identities.get(scope)
        if scope is ContextScope.GLOBAL or identity is not None:
            if scope not in available:
                available.append(scope)
            continue
        skipped.append(f"{scope.value}:identity_unavailable")
    if not available:
        available.append(ContextScope.GLOBAL)
    try:
        identity = validated_scope_identity(
            tuple(available),
            request.project,
            request.workspace_id,
            request.agent_id,
            request.user_id,
            request.session_id,
        )
    except ValueError as exc:
        raise MemoryContextValidationError(str(exc)) from exc
    if request.workspace_id is None:
        skipped.append("WORKSPACE:identity_unavailable")
    return identity, tuple(available), tuple(skipped)


def route_scopes(
    request: RecallRequest,
    resolved_scopes: tuple[ContextScope, ...],
    *,
    project: str | None,
) -> tuple[ContextScope, ...]:
    """Preserve STRICT lanes while deriving AUTO lanes per project route."""
    if request.scope_mode is RecallScopeMode.STRICT:
        return resolved_scopes
    scopes: list[ContextScope] = []
    if project is not None:
        scopes.append(ContextScope.PROJECT)
    for scope, identity in (
        (ContextScope.AGENT, request.agent_id),
        (ContextScope.SESSION, request.session_id),
        (ContextScope.USER, request.user_id),
    ):
        if identity is not None:
            scopes.append(scope)
    scopes.append(ContextScope.GLOBAL)
    return tuple(dict.fromkeys(scopes))


def historical_lifecycle_statuses(
    request: RecallRequest,
) -> tuple[ContextRecallLifecycleStatus, ...]:
    """Include stored lifecycle rows needed for as-of temporal filtering."""
    if request.include_lifecycle_statuses:
        return request.include_lifecycle_statuses
    return (
        ContextRecallLifecycleStatus.CURRENT,
        ContextRecallLifecycleStatus.ACTIVE,
        ContextRecallLifecycleStatus.SAVED,
        ContextRecallLifecycleStatus.SAVED_WITH_WARNINGS,
        ContextRecallLifecycleStatus.REDACTED_AND_SAVED,
        ContextRecallLifecycleStatus.REVIEWED,
        ContextRecallLifecycleStatus.SUPERSEDED,
        ContextRecallLifecycleStatus.ARCHIVED,
    )


def deduplicate_matches(
    matches: Sequence[RecallMatch],
    limit: int,
) -> list[RecallMatch]:
    """Deduplicate canonical contexts while preserving affinity priority."""
    selected: dict[str, RecallMatch] = {}
    for item in matches:
        key = item.provenance.canonical_context_id
        existing = selected.get(key)
        if existing is None or match_order_key(item) < match_order_key(existing):
            selected[key] = item
    return sorted(selected.values(), key=match_order_key)[:limit]


def match_order_key(item: RecallMatch) -> tuple[int, float, float, str]:
    """Return deterministic affinity, confidence, score, and identity order."""
    affinity_order = {
        RecallProjectAffinity.PRIMARY: 0,
        RecallProjectAffinity.RELATED: 1,
        RecallProjectAffinity.GLOBAL: 2,
    }
    return (
        affinity_order[item.provenance.project_affinity],
        -item.provenance.confidence,
        -item.match.score,
        item.provenance.canonical_context_id,
    )


def has_confident(matches: Sequence[RecallMatch]) -> bool:
    """Return whether one match has explicit evidence above the policy bound."""
    return any(item.provenance.confidence >= CONFIDENCE_THRESHOLD for item in matches)


def match_confidence(match: ContextSearchMatch, *, exact: bool) -> float:
    """Derive bounded confidence from existing lane evidence without new ranking."""
    if exact:
        return 1.0
    evidence_scores = tuple(
        min(max(float(value), 0.0), 1.0)
        for value in (
            match.score,
            match.fts_score,
            match.vector_score,
            match.graph_score,
        )
        if value is not None
    )
    score = max(evidence_scores, default=0.0)
    evidence_count = len(evidence_scores) - 1
    if evidence_count >= 2:
        score = min(1.0, score + 0.1)
    return score


def lifecycle_eligible(match: ContextSearchMatch) -> bool:
    """Return whether a match is in the default durable recall lifecycle."""
    return (
        not match.context.is_archived
        and match.context.status.value in ContextStorageStatus.default_recall_values()
    )


def metadata_text(match: ContextSearchMatch, key: str) -> str | None:
    """Read an optional revision string without inventing freshness."""
    value: JSONValue | None = match.context.context_metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def memory_authority(match: ContextSearchMatch) -> str:
    """Return declared source authority or explicit UNKNOWN."""
    declared = metadata_text(match, "authority") or metadata_text(
        match, "source_of_truth"
    )
    if declared is None:
        return "UNKNOWN"
    normalized = declared.upper().replace("-", "_").replace(" ", "_")
    return (
        normalized
        if normalized
        in {
            "CANONICAL",
            "CURRENT_EVIDENCE",
            "DERIVED",
            "HISTORICAL",
            "REFERENCE",
            "UNKNOWN",
        }
        else "UNKNOWN"
    )


def pack_is_degraded(
    warnings: Sequence[str],
    effective_strategy: RagStrategy,
    requested_strategy: RagStrategy,
) -> bool:
    """Classify observable retrieval degradation from existing pack evidence."""
    if (
        requested_strategy in {RagStrategy.HYBRID, RagStrategy.VECTOR_ONLY}
        and effective_strategy is RagStrategy.FTS_ONLY
    ):
        return True
    markers = ("degraded", "unavailable", "reindex_required", "disabled")
    return any(
        any(marker in warning.casefold() for marker in markers) for warning in warnings
    )


def normalize_identity(value: str | None) -> str | None:
    """Normalize an optional identity without collapsing unrelated fields."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def selector_kind(request: RecallRequest) -> str | None:
    """Return the exact selector kind represented by one request."""
    selector = request.selector
    if selector is None:
        return None
    if selector.note_id is not None and selector.note_id.strip():
        return "note_id"
    if selector.path is not None and selector.path.strip():
        return "path"
    return "logical_identity"


def exception_name(exc: Exception) -> str:
    """Return a bounded exception class name for trace warnings."""
    return type(exc).__name__[:80]


def record_stage_state(
    trace: RecallStageTrace,
    warnings: list[str],
    degraded_subsystems: list[str],
) -> None:
    """Accumulate stage warnings and degradation markers."""
    warnings.extend(trace.warnings)
    if trace.degraded:
        degraded_subsystems.append(trace.route.value)
