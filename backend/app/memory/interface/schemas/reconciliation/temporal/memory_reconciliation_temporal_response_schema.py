"""Strict temporal recall response schemas for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, TypeAdapter

from app.memory.domain.entities.memory_reconciliation import MemoryTemporalRecallPack
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryTemporalRecallMode,
)
from app.memory.domain.types.context_payload_types import ContextSearchMatchPayload
from app.memory.interface.schemas.context.context_mapping import match_payload
from app.memory.interface.schemas.context.context_search_schema import (
    ContextSearchMatchResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.schemas.datetime_schemas import AwareTimestamp

_MATCH_PAYLOAD_ADAPTER = TypeAdapter(ContextSearchMatchPayload)


class MemoryTemporalStateResponse(StrictSchemaModel):
    """Temporal and reconciliation overlay attached to one Context match."""

    context_id: Annotated[
        str,
        Field(
            description="Context identifier for this memory temporal state response."
        ),
    ]
    recorded_at: Annotated[
        AwareTimestamp,
        Field(description="Recorded at for this memory temporal state response."),
    ]
    observed_at: Annotated[
        AwareTimestamp | None,
        Field(description="Observed at for this memory temporal state response."),
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        Field(description="Valid from for this memory temporal state response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        Field(description="Valid to for this memory temporal state response."),
    ]
    is_current: Annotated[
        bool, Field(description="Is current for this memory temporal state response.")
    ]
    conflict_set_ids: Annotated[
        list[str],
        Field(
            description="Conflict set identifiers for this memory temporal state response."
        ),
    ]
    superseded_by: Annotated[
        list[str],
        Field(description="Superseded by for this memory temporal state response."),
    ]
    supersedes: Annotated[
        list[str],
        Field(description="Supersedes for this memory temporal state response."),
    ]
    relation_summary: Annotated[
        list[str],
        Field(description="Relation summary for this memory temporal state response."),
    ]


class MemoryTemporalRecallMatchResponse(StrictSchemaModel):
    """One ranked Context match with current/historical memory metadata."""

    match: Annotated[
        ContextSearchMatchResponse,
        Field(description="Match for this memory temporal recall match response."),
    ]
    temporal_state: Annotated[
        MemoryTemporalStateResponse | None,
        Field(
            description="Temporal state for this memory temporal recall match response."
        ),
    ]
    is_current: Annotated[
        bool,
        Field(description="Is current for this memory temporal recall match response."),
    ]
    conflict_set_ids: Annotated[
        list[str],
        Field(
            description="Conflict set identifiers for this memory temporal recall match response."
        ),
    ]
    superseded_by: Annotated[
        list[str],
        Field(
            description="Superseded by for this memory temporal recall match response."
        ),
    ]
    supersedes: Annotated[
        list[str],
        Field(description="Supersedes for this memory temporal recall match response."),
    ]
    relation_summary: Annotated[
        list[str],
        Field(
            description="Relation summary for this memory temporal recall match response."
        ),
    ]


class MemoryTemporalRecallResponse(StrictSchemaModel):
    """Context recall result filtered through an explicit temporal perspective."""

    query: Annotated[
        str, Field(description="Query for this memory temporal recall response.")
    ]
    mode: Annotated[
        MemoryTemporalRecallMode,
        Field(description="Mode for this memory temporal recall response."),
    ]
    as_of: Annotated[
        AwareTimestamp | None,
        Field(description="As of for this memory temporal recall response."),
    ]
    strategy: Annotated[
        str, Field(description="Strategy for this memory temporal recall response.")
    ]
    effective_strategy: Annotated[
        str,
        Field(
            description="Effective strategy for this memory temporal recall response."
        ),
    ]
    warnings: Annotated[
        list[str],
        Field(description="Warnings for this memory temporal recall response."),
    ]
    recall_scopes: Annotated[
        list[str],
        Field(description="Recall scopes for this memory temporal recall response."),
    ]
    matches: Annotated[
        list[MemoryTemporalRecallMatchResponse],
        Field(description="Matches for this memory temporal recall response."),
    ]
    context_pack: Annotated[
        str, Field(description="Context pack for this memory temporal recall response.")
    ]

    @classmethod
    def from_entity(
        cls,
        value: MemoryTemporalRecallPack,
    ) -> MemoryTemporalRecallResponse:
        """Validate one temporal recall result as a strict HTTP response.

        Args:
            value: Value.

        Returns:
            MemoryTemporalRecallResponse: Operation result.
        """
        matches = [
            MemoryTemporalRecallMatchResponse(
                match=ContextSearchMatchResponse.model_validate_json(
                    _MATCH_PAYLOAD_ADAPTER.dump_json(match_payload(item.match))
                ),
                temporal_state=(
                    None
                    if item.temporal_state is None
                    else MemoryTemporalStateResponse(
                        context_id=item.temporal_state.context_id,
                        recorded_at=item.temporal_state.recorded_at,
                        observed_at=item.temporal_state.observed_at,
                        valid_from=item.temporal_state.valid_from,
                        valid_to=item.temporal_state.valid_to,
                        is_current=item.temporal_state.is_current,
                        conflict_set_ids=list(item.temporal_state.conflict_set_ids),
                        superseded_by=list(item.temporal_state.superseded_by),
                        supersedes=list(item.temporal_state.supersedes),
                        relation_summary=list(item.temporal_state.relation_summary),
                    )
                ),
                is_current=item.is_current,
                conflict_set_ids=list(item.conflict_set_ids),
                superseded_by=list(item.superseded_by),
                supersedes=list(item.supersedes),
                relation_summary=list(item.relation_summary),
            )
            for item in value.matches
        ]
        return cls(
            query=value.query,
            mode=value.mode,
            as_of=value.as_of,
            strategy=value.strategy.value,
            effective_strategy=value.effective_strategy.value,
            warnings=list(value.warnings),
            recall_scopes=[item.value for item in value.recall_scopes],
            matches=matches,
            context_pack=value.context_pack,
        )
