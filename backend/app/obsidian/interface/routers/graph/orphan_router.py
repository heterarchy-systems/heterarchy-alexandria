"""Obsidian graph orphan census, status, acknowledgement, and suggestion routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.obsidian.application.graph.diagnostics.obsidian_graph_orphan_census_service import (
    ObsidianGraphOrphanCensusService,
)
from app.obsidian.domain.entities.obsidian_orphan_census import (
    ObsidianGraphOrphanEntry,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.interface.schemas.obsidian.obsidian_orphan_census_schema import (
    ObsidianGraphOrphanAcknowledgeRequest,
    ObsidianGraphOrphanCensusResponse,
    ObsidianGraphOrphanEntryResponse,
    ObsidianGraphOrphanListRequest,
    ObsidianGraphOrphanStatusRequest,
    ObsidianGraphRelationSuggestionResponse,
    ObsidianGraphRelationSuggestionsResponse,
    ObsidianGraphSuggestRelationsRequest,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter()


def _orphan_entry_response(
    orphan: ObsidianGraphOrphanEntry,
) -> ObsidianGraphOrphanEntryResponse:
    """Map one domain orphan census entry into its API response schema.

    Args:
        orphan: Domain orphan census entry.

    Returns:
        API response representation of the orphan entry.
    """
    return ObsidianGraphOrphanEntryResponse(
        note_id=orphan.note_id,
        relative_path=orphan.relative_path,
        title=orphan.title,
        project=orphan.project,
        status=orphan.status,
        in_degree=orphan.in_degree,
        out_degree=orphan.out_degree,
        canonical_parent_count=orphan.canonical_parent_count,
        has_wikilink_connectivity=orphan.has_wikilink_connectivity,
        debt_kinds=list(orphan.debt_kinds),
        has_declared_relations=orphan.has_declared_relations,
        acknowledgement_reason=orphan.acknowledgement_reason,
        first_seen_at=(
            None if orphan.first_seen_at is None else orphan.first_seen_at.isoformat()
        ),
        last_seen_at=(
            None if orphan.last_seen_at is None else orphan.last_seen_at.isoformat()
        ),
        first_seen_run_id=orphan.first_seen_run_id,
        last_seen_run_id=orphan.last_seen_run_id,
        graph_run_id=orphan.graph_run_id,
    )


@router.post(
    "/graph/orphans",
    response_model=ObsidianGraphOrphanCensusResponse,
    status_code=status.HTTP_200_OK,
    summary="List graph orphan debt",
    description=(
        "Enumerate measured graph orphan debt from the projection snapshot. "
        "This records bounded first/last-seen diagnostic metadata; it does not "
        "mutate canonical Markdown or graph links."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_graph_orphans(
    request: Annotated[
        ObsidianGraphOrphanListRequest,
        json_mode_body(ObsidianGraphOrphanListRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
    index_repo: Annotated[
        IObsidianIndexRepository,
        Depends(Provide[ApplicationContainer.obsidian.index_repo]),
    ],
) -> ObsidianGraphOrphanCensusResponse:
    """Return one deterministic orphan census page.

    Args:
        request: Orphan list pagination and project filter request.
        service: Graph orphan census service.
        index_repo: Obsidian note index repository.

    Returns:
        Bounded page of orphan census entries and cursor metadata.
    """
    result = await service.list_orphans(
        project=request.project,
        limit=request.limit,
        cursor=request.cursor,
        index_repository=index_repo,
    )
    return ObsidianGraphOrphanCensusResponse(
        orphans=[_orphan_entry_response(orphan) for orphan in result.orphans],
        total_orphans=result.total_orphans,
        next_cursor=result.next_cursor,
    )


@router.post(
    "/graph/orphans/status",
    response_model=ObsidianGraphOrphanEntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get exact graph orphan status",
    description=(
        "Diagnose one exact note id through the current Rust-owned graph "
        "projection and preserve durable census history."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_graph_orphan_status(
    request: Annotated[
        ObsidianGraphOrphanStatusRequest,
        json_mode_body(ObsidianGraphOrphanStatusRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
    index_repo: Annotated[
        IObsidianIndexRepository,
        Depends(Provide[ApplicationContainer.obsidian.index_repo]),
    ],
) -> ObsidianGraphOrphanEntryResponse:
    """Return one exact current orphan status without changing census history.

    Args:
        request: Exact note id status request.
        service: Graph orphan census service.
        index_repo: Obsidian note index repository.

    Returns:
        Current orphan status and durable census metadata for the note.
    """
    orphan = await service.get_orphan_status(
        note_id=request.note_id,
        index_repository=index_repo,
    )
    return _orphan_entry_response(orphan)


@router.post(
    "/graph/orphans/acknowledge",
    response_model=ObsidianGraphOrphanEntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge one graph orphan",
    description=(
        "Persist a durable census acknowledgement for one standalone note so "
        "future census pages report the acknowledged status."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def acknowledge_graph_orphan(
    request: Annotated[
        ObsidianGraphOrphanAcknowledgeRequest,
        json_mode_body(ObsidianGraphOrphanAcknowledgeRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
) -> ObsidianGraphOrphanEntryResponse:
    """Persist one orphan acknowledgement.

    Args:
        request: Orphan acknowledgement decision and reason request.
        service: Graph orphan census service.

    Returns:
        Persisted orphan acknowledgement entry response.
    """
    acknowledgement = await service.acknowledge_orphan(
        note_id=request.note_id,
        decision=request.decision,
        reason=request.reason,
        acknowledged_by=request.acknowledged_by,
    )
    return ObsidianGraphOrphanEntryResponse(
        note_id=acknowledgement.note_id,
        relative_path="",
        title="",
        project=None,
        status=acknowledgement.decision,
        in_degree=0,
        out_degree=0,
        canonical_parent_count=0,
        has_wikilink_connectivity=False,
        debt_kinds=[],
        has_declared_relations=False,
        acknowledgement_reason=acknowledgement.reason,
    )


@router.post(
    "/graph/orphans/suggest-relations",
    response_model=ObsidianGraphRelationSuggestionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Suggest relations for one note",
    description=(
        "Propose deterministic, evidence-backed relation candidates for one "
        "seed note; suggestions never mutate anything."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def suggest_graph_relations(
    request: Annotated[
        ObsidianGraphSuggestRelationsRequest,
        json_mode_body(ObsidianGraphSuggestRelationsRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
    index_repo: Annotated[
        IObsidianIndexRepository,
        Depends(Provide[ApplicationContainer.obsidian.index_repo]),
    ],
) -> ObsidianGraphRelationSuggestionsResponse:
    """Return deterministic relation suggestions for one seed note.

    Args:
        request: Seed note selector and candidate limit request.
        service: Graph orphan census service.
        index_repo: Obsidian note index repository.

    Returns:
        Deterministic relation suggestions for the seed note.
    """
    result = await service.suggest_relations(
        note_id=request.note_id,
        path=request.path,
        limit=request.limit,
        index_repository=index_repo,
    )
    return ObsidianGraphRelationSuggestionsResponse(
        note_id=result.note_id,
        relative_path=result.relative_path,
        suggestions=[
            ObsidianGraphRelationSuggestionResponse(
                candidate_note_id=s.candidate_note_id,
                candidate_path=s.candidate_path,
                candidate_title=s.candidate_title,
                relation=s.relation,
                confidence=s.confidence,
                shared_tags=list(s.shared_tags),
                shared_neighbor_count=s.shared_neighbor_count,
                title_overlap_tokens=list(s.title_overlap_tokens),
                explanation=s.explanation,
            )
            for s in result.suggestions
        ],
    )
