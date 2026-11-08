"""Exact relation projection and bidirectional readback verification."""

from __future__ import annotations

from dataclasses import dataclass

from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.notes.relations.contracts import issue
from app.obsidian.application.notes.relations.relation_enums import (
    RelationIssueCapability,
    RelationIssueCode,
    RelationProjectionStatus,
)
from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateIssue
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianRelationType
from app.obsidian.domain.event_enum.obsidian_graph_enums import ObsidianGraphDirection
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphVerificationDTO:
    """Bounded graph readback evidence for one directed relation."""

    edge_id: str | None
    projection_run_id: str | None
    projection_status: str
    source_related: bool
    target_related: bool
    warnings: tuple[ObsidianRelateIssue, ...] = ()


class GraphVerifier:
    """Verify the exact projected edge and both graph read directions."""

    def __init__(
        self,
        *,
        graph_service: ObsidianGraphService,
        graph_repository: IObsidianGraphProjectionRepository,
    ) -> None:
        """Create one verifier over the existing graph authorities.

        Args:
            graph_service: Existing relation traversal owner.
            graph_repository: Existing active projection read authority.
        """
        self._graph_service = graph_service
        self._graph_repository = graph_repository

    async def verify(
        self,
        *,
        source_note_id: str,
        target_note_id: str,
        relation: ObsidianRelationType,
    ) -> GraphVerificationDTO:
        """Read the exact active edge and both directional note views.

        Args:
            source_note_id: Canonical source note identifier.
            target_note_id: Canonical target note identifier.
            relation: Exact relation enum identity to verify.

        Returns:
            Projection and bounded directional readback evidence.
        """
        warnings: list[ObsidianRelateIssue] = []
        try:
            state = await self._graph_repository.state()
            edge = next(
                (
                    item
                    for item in state.projection.edges
                    if item.source_note_id == source_note_id
                    and item.target_note_id == target_note_id
                    and item.relation is relation
                ),
                None,
            )
        except Exception as exc:
            return GraphVerificationDTO(
                edge_id=None,
                projection_run_id=None,
                projection_status=RelationProjectionStatus.UNAVAILABLE.value,
                source_related=False,
                target_related=False,
                warnings=(
                    issue(
                        code=RelationIssueCode.GRAPH_PROJECTION_READ_FAILED,
                        cause=f"{type(exc).__name__}: {exc}",
                        affected_capability=RelationIssueCapability.GRAPH_PROJECTION,
                        retryable=True,
                        safe_next_action="restore graph projection readiness and replay the same idempotency key",
                    ),
                ),
            )

        source_related = False
        target_related = False
        try:
            source_related = any(
                item.note.note_id == target_note_id
                and item.relation is relation
                and item.direction == ObsidianGraphDirection.OUTGOING.value
                for item in await self._graph_service.related_notes(
                    source_note_id,
                    limit=50,
                )
            )
            target_related = any(
                item.note.note_id == source_note_id
                and item.relation is relation
                and item.direction == ObsidianGraphDirection.INCOMING.value
                for item in await self._graph_service.related_notes(
                    target_note_id,
                    limit=50,
                )
            )
        except Exception as exc:
            warnings.append(
                issue(
                    code=RelationIssueCode.GRAPH_RELATED_READ_FAILED,
                    cause=str(exc),
                    affected_capability=RelationIssueCapability.RELATED_NOTE_READ,
                    retryable=True,
                    safe_next_action="restore graph read readiness and replay the same idempotency key",
                )
            )

        projection_status = (
            RelationProjectionStatus.READY.value
            if edge is not None
            else RelationProjectionStatus.STALE.value
        )
        if edge is None:
            warnings.append(
                issue(
                    code=RelationIssueCode.GRAPH_EDGE_NOT_VERIFIED,
                    cause="the exact directed relation is absent from the active projection",
                    affected_capability=RelationIssueCapability.GRAPH_PROJECTION,
                    retryable=True,
                    safe_next_action="retry the same idempotency key after graph projection rebuild",
                )
            )
        return GraphVerificationDTO(
            edge_id=None if edge is None else edge.edge_id,
            projection_run_id=state.run_id,
            projection_status=projection_status,
            source_related=source_related,
            target_related=target_related,
            warnings=tuple(warnings),
        )
