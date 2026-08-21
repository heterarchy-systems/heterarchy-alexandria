"""Strict temporal recall response schemas for memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.memory_reconciliation import MemoryTemporalRecallPack
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryTemporalRecallMode,
)
from app.memory.domain.types.context_payload_types import ContextSearchMatchPayload
from app.memory.interface.schemas.context.context_mapping import match_payload
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextSearchMatchResponse,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.schemas.datetime_schemas import AwareTimestamp
from pydantic import TypeAdapter

_MATCH_PAYLOAD_ADAPTER = TypeAdapter(ContextSearchMatchPayload)


class MemoryTemporalStateResponse(StrictSchemaModel):
    """Temporal and reconciliation overlay attached to one Context match."""

    context_id: Annotated[
        str,
        described_field("Context identifier for this memory temporal state response."),
    ]
    recorded_at: Annotated[
        AwareTimestamp,
        described_field("Recorded at for this memory temporal state response."),
    ]
    observed_at: Annotated[
        AwareTimestamp | None,
        described_field("Observed at for this memory temporal state response."),
    ]
    valid_from: Annotated[
        AwareTimestamp | None,
        described_field("Valid from for this memory temporal state response."),
    ]
    valid_to: Annotated[
        AwareTimestamp | None,
        described_field("Valid to for this memory temporal state response."),
    ]
    is_current: Annotated[
        bool, described_field("Is current for this memory temporal state response.")
    ]
    conflict_set_ids: Annotated[
        list[str],
        described_field(
            "Conflict set identifiers for this memory temporal state response."
        ),
    ]
    superseded_by: Annotated[
        list[str],
        described_field("Superseded by for this memory temporal state response."),
    ]
    supersedes: Annotated[
        list[str],
        described_field("Supersedes for this memory temporal state response."),
    ]
    relation_summary: Annotated[
        list[str],
        described_field("Relation summary for this memory temporal state response."),
    ]


class MemoryTemporalRecallMatchResponse(StrictSchemaModel):
    """One ranked Context match with current/historical memory metadata."""

    match: Annotated[
        ContextSearchMatchResponse,
        described_field("Match for this memory temporal recall match response."),
    ]
    temporal_state: Annotated[
        MemoryTemporalStateResponse | None,
        described_field(
            "Temporal state for this memory temporal recall match response."
        ),
    ]
    is_current: Annotated[
        bool,
        described_field("Is current for this memory temporal recall match response."),
    ]
    conflict_set_ids: Annotated[
        list[str],
        described_field(
            "Conflict set identifiers for this memory temporal recall match response."
        ),
    ]
    superseded_by: Annotated[
        list[str],
        described_field(
            "Superseded by for this memory temporal recall match response."
        ),
    ]
    supersedes: Annotated[
        list[str],
        described_field("Supersedes for this memory temporal recall match response."),
    ]
    relation_summary: Annotated[
        list[str],
        described_field(
            "Relation summary for this memory temporal recall match response."
        ),
    ]


class MemoryTemporalRecallResponse(StrictSchemaModel):
    """Context recall result filtered through an explicit temporal perspective."""

    query: Annotated[
        str, described_field("Query for this memory temporal recall response.")
    ]
    mode: Annotated[
        MemoryTemporalRecallMode,
        described_field("Mode for this memory temporal recall response."),
    ]
    as_of: Annotated[
        AwareTimestamp | None,
        described_field("As of for this memory temporal recall response."),
    ]
    strategy: Annotated[
        str, described_field("Strategy for this memory temporal recall response.")
    ]
    effective_strategy: Annotated[
        str,
        described_field("Effective strategy for this memory temporal recall response."),
    ]
    warnings: Annotated[
        list[str], described_field("Warnings for this memory temporal recall response.")
    ]
    recall_scopes: Annotated[
        list[str],
        described_field("Recall scopes for this memory temporal recall response."),
    ]
    matches: Annotated[
        list[MemoryTemporalRecallMatchResponse],
        described_field("Matches for this memory temporal recall response."),
    ]
    context_pack: Annotated[
        str, described_field("Context pack for this memory temporal recall response.")
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
