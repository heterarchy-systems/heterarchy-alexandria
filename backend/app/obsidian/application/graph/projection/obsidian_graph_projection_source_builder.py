"""Build deterministic graph projection batches from the Obsidian index."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionBatch,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionIssue,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionSourceMetrics,
    ObsidianGraphProjectionSourceSnapshot,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianEdge, ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphProjectionIssueCode,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_source_repository import (
    IObsidianGraphProjectionSourceRepository,
)


class ObsidianGraphProjectionSourceBuilder:
    """Map typed relational-index rows into deterministic projection batches."""

    def __init__(
        self,
        source: IObsidianGraphProjectionSourceRepository,
        batch_size: int = 500,
    ) -> None:
        """Create the projection source builder.

        Args:
            source: Read-only typed projection source.
            batch_size: Maximum nodes and edges included in each batch.

        Raises:
            ValueError: When the requested batch size is not positive.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        self._source = source
        self._batch_size = batch_size

    async def build(self) -> ObsidianGraphProjectionSourceSnapshot:
        """Build one stable projection snapshot from the current index state.

        Returns:
            Immutable projection, bounded batches, and explicit source issues.
        """
        notes = await self._source.list_projection_notes()
        edges = await self._source.list_projection_edges()
        indexed_notes = tuple(
            sorted(
                (
                    note
                    for note in notes
                    if note.index_status is ObsidianIndexStatus.INDEXED
                ),
                key=lambda note: note.note_id,
            )
        )
        notes_by_id = {note.note_id: note for note in indexed_notes}
        notes_by_path = {note.relative_path: note for note in indexed_notes}
        notes_by_link_name = _notes_by_link_name(indexed_notes)
        projection_nodes = tuple(_projection_node(note) for note in indexed_notes)
        projection_edges, missing_target_issues = _projection_edges(
            edges,
            notes_by_id=notes_by_id,
            notes_by_path=notes_by_path,
            notes_by_link_name=notes_by_link_name,
        )
        issues = tuple(
            sorted(
                (*_index_error_issues(notes), *missing_target_issues),
                key=_issue_sort_key,
            )
        )
        projection = ObsidianGraphProjection(
            nodes=projection_nodes,
            edges=projection_edges,
        )
        return ObsidianGraphProjectionSourceSnapshot(
            projection=projection,
            batches=_batches(projection, batch_size=self._batch_size),
            issues=issues,
            metrics=ObsidianGraphProjectionSourceMetrics(
                scanned=len(notes) + len(edges),
                indexed=len(projection_nodes) + len(projection_edges),
                skipped=(len(notes) + len(edges))
                - (len(projection_nodes) + len(projection_edges)),
                errors=len(issues),
            ),
        )


def _projection_node(note: ObsidianNote) -> ObsidianGraphProjectionNode:
    return ObsidianGraphProjectionNode(
        note_id=note.note_id,
        relative_path=note.relative_path,
        alexandria_type=note.alexandria_type,
        title=note.title,
        status=note.status,
        project=note.project,
    )


def _projection_edges(
    edges: tuple[ObsidianEdge, ...],
    notes_by_id: dict[str, ObsidianNote],
    notes_by_path: dict[str, ObsidianNote],
    notes_by_link_name: dict[str, tuple[ObsidianNote, ...]],
) -> tuple[
    tuple[ObsidianGraphProjectionEdge, ...],
    tuple[ObsidianGraphProjectionIssue, ...],
]:
    projected: list[ObsidianGraphProjectionEdge] = []
    issues: list[ObsidianGraphProjectionIssue] = []
    for edge in sorted(edges, key=lambda item: item.edge_id):
        source = notes_by_id.get(edge.source_note_id)
        if source is None:
            continue
        target = (
            notes_by_id.get(edge.target_note_id)
            if edge.target_note_id is not None
            else None
        ) or notes_by_path.get(edge.target_path)
        ambiguous = False
        if target is None:
            candidates = notes_by_link_name.get(_link_name(edge.target_path), ())
            if len(candidates) == 1:
                target = candidates[0]
            elif len(candidates) > 1:
                ambiguous = True
        if target is None:
            issues.append(
                ObsidianGraphProjectionIssue(
                    code=(
                        ObsidianGraphProjectionIssueCode.AMBIGUOUS_TARGET_NOTE
                        if ambiguous
                        else ObsidianGraphProjectionIssueCode.MISSING_TARGET_NOTE
                    ),
                    relative_path=edge.target_path,
                    note_id=edge.source_note_id,
                    edge_id=edge.edge_id,
                    detail=(
                        "edge target matches multiple healthy Obsidian notes"
                        if ambiguous
                        else "edge target is absent from the healthy Obsidian index"
                    ),
                )
            )
            continue
        projected.append(
            ObsidianGraphProjectionEdge(
                edge_id=edge.edge_id,
                source_note_id=edge.source_note_id,
                source_path=source.relative_path,
                target_note_id=target.note_id,
                target_path=target.relative_path,
                relation=edge.relation,
                confidence=edge.confidence,
                source_kind=edge.source_kind,
            )
        )
    return tuple(projected), tuple(issues)


def _notes_by_link_name(
    notes: tuple[ObsidianNote, ...],
) -> dict[str, tuple[ObsidianNote, ...]]:
    grouped: defaultdict[str, list[ObsidianNote]] = defaultdict(list)
    for note in notes:
        names = {_link_name(note.relative_path), note.title.strip().casefold()}
        aliases = note.frontmatter.get("aliases")
        if isinstance(aliases, str):
            names.add(aliases.strip().casefold())
        elif isinstance(aliases, list):
            names.update(
                alias.strip().casefold()
                for alias in aliases
                if isinstance(alias, str) and alias.strip()
            )
        for name in names:
            if name:
                grouped[name].append(note)
    return {
        name: tuple(sorted(values, key=lambda item: item.relative_path))
        for name, values in grouped.items()
    }


def _link_name(path: str) -> str:
    return PurePosixPath(path).stem.strip().casefold()


def _index_error_issues(
    notes: tuple[ObsidianNote, ...],
) -> tuple[ObsidianGraphProjectionIssue, ...]:
    return tuple(
        ObsidianGraphProjectionIssue(
            code=ObsidianGraphProjectionIssueCode.INDEX_ERROR,
            relative_path=note.relative_path,
            note_id=note.note_id,
            detail="indexed note is in error state",
        )
        for note in notes
        if note.index_status is ObsidianIndexStatus.ERROR
    )


def _batches(
    projection: ObsidianGraphProjection,
    batch_size: int,
) -> tuple[ObsidianGraphProjectionBatch, ...]:
    batch_count = max(
        _batch_count(len(projection.nodes), batch_size),
        _batch_count(len(projection.edges), batch_size),
    )
    return tuple(
        ObsidianGraphProjectionBatch(
            batch_index=batch_index,
            projection=ObsidianGraphProjection(
                nodes=projection.nodes[
                    batch_index * batch_size : (batch_index + 1) * batch_size
                ],
                edges=projection.edges[
                    batch_index * batch_size : (batch_index + 1) * batch_size
                ],
            ),
        )
        for batch_index in range(batch_count)
    )


def _batch_count(item_count: int, batch_size: int) -> int:
    return (item_count + batch_size - 1) // batch_size


def _issue_sort_key(issue: ObsidianGraphProjectionIssue) -> tuple[str, str, str]:
    return (
        issue.code.value,
        issue.relative_path,
        issue.edge_id or issue.note_id or "",
    )
