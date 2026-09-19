"""Read-only graph issue listing backed by the deterministic compute authority."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
    ObsidianGraphIssueDetail,
    ObsidianGraphIssueListQuery,
    ObsidianGraphIssueListResult,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.repositories.obsidian_graph_projection_compute_provider import (
    IObsidianGraphProjectionComputeProvider,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_source_repository import (
    IObsidianGraphProjectionSourceRepository,
)
from app.shared.compute.native_text_hashing import hash_text


class ObsidianGraphIssueListService:
    """List graph projection issues with exact source and target detail.

    The listing recomputes the projection from the current index state through
    the same deterministic compute authority used by rebuild, so every issue
    carries the exact source note, target path, and relation without any
    automatic repair. This is a read-only diagnostic; it never creates notes
    or mutates Markdown, PostgreSQL, or the active projection.
    """

    def __init__(
        self,
        source: IObsidianGraphProjectionSourceRepository,
        compute_provider: IObsidianGraphProjectionComputeProvider,
        projection_status: Callable[[], Awaitable[ObsidianGraphProjectionStatusReport]],
        batch_size: int = 500,
    ) -> None:
        """Create the graph issue list service.

        Args:
            source: Read-only typed projection source rows.
            compute_provider: Deterministic projection compute authority.
            projection_status: Active projection status reader for run ids.
            batch_size: Maximum nodes and edges included in one compute batch.

        Raises:
            ValueError: When the requested batch size is not positive.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        self._source = source
        self._compute_provider = compute_provider
        self._projection_status = projection_status
        self._batch_size = batch_size

    async def list_issues(
        self,
        query: ObsidianGraphIssueListQuery,
    ) -> ObsidianGraphIssueListResult:
        """List issues for the current index state with exact detail.

        Args:
            query: Bounded filter and pagination query.

        Returns:
            One bounded page of issue detail in edge-id order.
        """
        notes = await self._source.list_projection_notes()
        edges = await self._source.list_projection_edges()
        snapshot = self._compute_provider.compute(notes, edges, self._batch_size)
        run_id = await self._active_run_id()

        edge_by_id = {edge.edge_id: edge for edge in edges}
        notes_by_id = {note.note_id: note for note in notes}
        details: list[ObsidianGraphIssueDetail] = []
        for issue in snapshot.issues:
            if issue.edge_id is None:
                continue
            edge = edge_by_id.get(issue.edge_id)
            if edge is None:
                continue
            details.append(
                ObsidianGraphIssueDetail(
                    issue_id=_issue_id(issue.code.value, issue.edge_id),
                    code=issue.code.value,
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    source_path=edge.source_path,
                    source_title=_source_title(notes_by_id, edge.source_note_id),
                    target_path=edge.target_path,
                    relation=edge.relation.value,
                    detail=issue.detail,
                    projection_run_id=run_id,
                )
            )
        details.sort(key=lambda item: item.edge_id)

        filtered = [
            item
            for item in details
            if (query.code is None or item.code == query.code)
            and (
                query.source_note_id is None
                or item.source_note_id == query.source_note_id
            )
            and (query.source_path is None or item.source_path == query.source_path)
        ]
        if query.cursor is not None:
            filtered = [item for item in filtered if item.edge_id > query.cursor]
        page = filtered[: query.limit]
        next_cursor = page[-1].edge_id if len(filtered) > query.limit else None
        return ObsidianGraphIssueListResult(
            issues=tuple(page),
            next_cursor=next_cursor,
            run_id=run_id,
        )

    async def _active_run_id(self) -> str | None:
        """Return the active projection run id without failing the listing.

        Returns:
            Active projection run id, or None when unavailable.
        """
        try:
            status: ObsidianGraphProjectionStatusReport = (
                await self._projection_status()
            )
        except (OSError, ValueError):
            return None
        return status.run_id


def _source_title(
    notes_by_id: dict[str, ObsidianNote],
    source_note_id: str,
) -> str | None:
    """Return the source note title when the row is present.

    Args:
        notes_by_id: Source notes keyed by identity.
        source_note_id: Source note identity.

    Returns:
        Source note title, or None when unknown.
    """
    note = notes_by_id.get(source_note_id)
    return note.title if note is not None else None


def _issue_id(code: str, edge_id: str) -> str:
    """Return the stable deterministic issue id for one graph issue.

    Args:
        code: Issue code.
        edge_id: Canonical edge identifier.

    Returns:
        Digest stable across projection runs for the same broken link.
    """
    return hash_text(f"{code}\x1f{edge_id}")
