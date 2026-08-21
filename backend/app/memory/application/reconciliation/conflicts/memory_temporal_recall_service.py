"""Reconciliation-aware current and historical Context recall."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.memory.application.reconciliation.conflicts.memory_temporal_recall_policy import (
    include_temporal_match,
    state_is_current,
)
from app.memory.application.retrieval.context_pack import build_context_pack
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.entities.context_read_models import ContextPack, ContextRecord
from app.memory.domain.entities.memory_reconciliation import (
    MemoryTemporalRecallMatch,
    MemoryTemporalRecallPack,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode
from app.memory.domain.repositories.reconciliation.memory_reconciliation_temporal_repository import (
    IMemoryReconciliationTemporalRepository,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import now_utc
from pydantic import TypeAdapter, ValidationError

_AWARE_TIMESTAMP_ADAPTER = TypeAdapter(AwareTimestamp)


class ContextTemporalSearchService(Protocol):
    """Minimal existing Context search surface required by temporal recall."""

    async def search(
        self,
        query: str,
        strategy: RagStrategy,
        limit: int,
        project: str | None = None,
        kind: ContextKind | None = None,
        include_scopes: list[ContextScope] | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None = None,
    ) -> ContextPack:
        """Return ranked Context matches through the established search use case.

        Args:
            query: Query.
            strategy: Strategy.
            limit: Limit.
            project: Project.
            kind: Kind.
            include_scopes: Include scopes.
            workspace_id: Workspace id.
            agent_id: Agent id.
            user_id: User id.
            session_id: Session id.
            include_lifecycle_statuses: Include lifecycle statuses.

        Returns:
            ContextPack: Operation result.
        """


class MemoryTemporalRecallService:
    """Apply temporal overlays to existing ranked Context search results."""

    def __init__(
        self,
        context_service: ContextTemporalSearchService,
        repository: IMemoryReconciliationTemporalRepository,
    ) -> None:
        self._context_service = context_service
        self._repository = repository

    async def recall(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        """Return ranked Context matches visible from one temporal perspective.

        Args:
            request: Request.

        Returns:
            MemoryTemporalRecallPack: Operation result.
        """
        query = request.query.strip()
        if not query:
            raise MemoryContextValidationError("temporal recall query is required")
        if request.limit < 1 or request.limit > 100:
            raise MemoryContextValidationError(
                "temporal recall limit must be between 1 and 100"
            )
        now = now_utc()
        as_of = _resolved_as_of(request, now=now)
        search_limit = (
            request.limit
            if request.mode is MemoryTemporalRecallMode.ALL
            else min(request.limit * 3, 100)
        )
        pack = await self._context_service.search(
            query=query,
            strategy=request.strategy,
            limit=search_limit,
            project=request.project,
            kind=request.kind,
            include_scopes=(
                list(request.include_scopes) if request.include_scopes else None
            ),
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            user_id=request.user_id,
            session_id=request.session_id,
            include_lifecycle_statuses=(
                list(request.include_lifecycle_statuses)
                if request.include_lifecycle_statuses
                else None
            ),
        )
        matches: list[MemoryTemporalRecallMatch] = []
        warnings = list(pack.warnings)
        conflict_ids: list[str] = []
        for match in pack.matches:
            state = await self._temporal_state(match.context)
            if not include_temporal_match(
                mode=request.mode,
                state=state,
                context=match.context,
                as_of=as_of,
                now=now,
            ):
                continue
            conflict_ids.extend(() if state is None else state.conflict_set_ids)
            matches.append(
                MemoryTemporalRecallMatch(
                    match=match,
                    temporal_state=state,
                    is_current=state_is_current(
                        state=state,
                        context=match.context,
                        now=now,
                    ),
                    conflict_set_ids=() if state is None else state.conflict_set_ids,
                    superseded_by=() if state is None else state.superseded_by,
                    supersedes=() if state is None else state.supersedes,
                    relation_summary=() if state is None else state.relation_summary,
                )
            )
            if len(matches) >= request.limit:
                break
        unique_conflicts = tuple(dict.fromkeys(conflict_ids))
        if unique_conflicts:
            warnings.append(
                "Temporal recall includes unresolved or recorded memory conflicts: "
                + ", ".join(unique_conflicts)
            )
        underlying_matches = [item.match for item in matches]
        return MemoryTemporalRecallPack(
            query=query,
            mode=request.mode,
            as_of=(
                as_of
                if request.mode is MemoryTemporalRecallMode.HISTORICAL
                else request.as_of
            ),
            strategy=pack.strategy,
            effective_strategy=pack.effective_strategy,
            warnings=tuple(warnings),
            recall_scopes=tuple(pack.recall_scopes),
            matches=tuple(matches),
            context_pack=build_context_pack(query, underlying_matches),
        )

    async def _temporal_state(
        self,
        context: ContextRecord,
    ) -> MemoryTemporalState | None:
        persisted = await self._repository.get_temporal_state(context.id)
        if persisted is not None:
            return persisted
        return temporal_state_from_context_metadata(context)


def temporal_state_from_context_metadata(
    context: ContextRecord,
) -> MemoryTemporalState | None:
    """Restore a temporal overlay from canonical Context frontmatter metadata.

    Args:
        context: Context.

    Returns:
        MemoryTemporalState | None: Operation result.
    """
    metadata = context.context_metadata
    recorded_at = _metadata_timestamp(metadata, "recorded_at")
    observed_at = _metadata_timestamp(metadata, "observed_at")
    valid_from = _metadata_timestamp(metadata, "valid_from")
    valid_to = _metadata_timestamp(metadata, "valid_to")
    conflict_set_ids = _metadata_strings(metadata, "conflict_set_ids")
    superseded_by = _single_metadata_id(metadata, "superseded_by_context_id")
    supersedes = _single_metadata_id(metadata, "supersedes_context_id")
    relation_summary = _metadata_relation_summary(metadata)
    has_overlay = any(
        (
            recorded_at,
            observed_at,
            valid_from,
            valid_to,
            conflict_set_ids,
            superseded_by,
            supersedes,
            relation_summary,
        )
    )
    if not has_overlay:
        return None
    return MemoryTemporalState(
        context_id=context.id,
        recorded_at=recorded_at or context.created_at,
        observed_at=observed_at,
        valid_from=valid_from,
        valid_to=valid_to,
        is_current=(not context.is_archived and valid_to is None and not superseded_by),
        conflict_set_ids=conflict_set_ids,
        superseded_by=superseded_by,
        supersedes=supersedes,
        relation_summary=relation_summary,
    )


def _resolved_as_of(
    request: MemoryTemporalRecallRequest,
    now: datetime,
) -> datetime:
    if request.mode is MemoryTemporalRecallMode.HISTORICAL and request.as_of is None:
        raise MemoryContextValidationError(
            "historical temporal recall requires an explicit as_of timestamp"
        )
    value = request.as_of or now
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryContextValidationError(
            "temporal recall as_of timestamp must include timezone information"
        )
    return value


def _metadata_timestamp(
    metadata: ContextMetadataPayload,
    key: str,
) -> datetime | None:
    value: JSONValue | None = metadata.get(key)
    if value is None:
        return None
    try:
        return _AWARE_TIMESTAMP_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def _metadata_strings(
    metadata: ContextMetadataPayload,
    key: str,
) -> tuple[str, ...]:
    value: JSONValue | None = metadata.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


def _single_metadata_id(
    metadata: ContextMetadataPayload,
    key: str,
) -> tuple[str, ...]:
    value: JSONValue | None = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        return ()
    normalized = value.strip()
    if not normalized.startswith("obsidian:"):
        normalized = f"obsidian:{normalized}"
    return (normalized,)


def _metadata_relation_summary(
    metadata: ContextMetadataPayload,
) -> tuple[str, ...]:
    summaries: list[str] = []
    for field in (
        "duplicates",
        "supports",
        "extends",
        "contradicts",
        "supersedes",
        "related",
    ):
        value: JSONValue | None = metadata.get(field)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            target = item.get("id")
            if isinstance(target, str) and target.strip():
                summaries.append(f"{field}:obsidian:{target.strip()}")
    return tuple(dict.fromkeys(summaries))
