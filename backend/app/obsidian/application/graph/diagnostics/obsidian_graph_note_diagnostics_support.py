"""Obsidian graph note diagnostics support."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildReport,
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianEdge, ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexStatus
from app.obsidian.infrastructure.markdown.paths import (
    safe_relative_path,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
)

GraphLinkValidationIssueCode = Literal[
    "missing_target_note",
    "ambiguous_target_note",
    "target_not_indexed",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphNoteSelector:
    """Exact note selector supplied at the diagnostics boundary."""

    note_id: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphNoteIndexDiagnostic:
    """Indexed-note existence and health for one diagnostics request."""

    exists: bool
    note_id: str | None = None
    relative_path: str | None = None
    title: str | None = None
    index_status: str | None = None
    error_message: str | None = None
    projection_included: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphResolvedTargetDiagnostic:
    """One outgoing edge that resolves to a healthy indexed note."""

    edge_id: str
    target_note_id: str
    target_path: str
    relation: str
    source_kind: str


@dataclass(slots=True, kw_only=True)
class ObsidianGraphUnresolvedTargetDiagnostic:
    """One outgoing edge target that cannot be projected as a stable note edge."""

    edge_id: str
    target_path: str
    relation: str
    source_kind: str
    code: GraphLinkValidationIssueCode
    detail: str
    target_note_id: str | None = None
    candidate_note_ids: tuple[str, ...] = field(default_factory=tuple)
    candidate_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize candidate collections to immutable tuples."""
        self.candidate_note_ids = tuple(self.candidate_note_ids)
        self.candidate_paths = tuple(self.candidate_paths)


@dataclass(slots=True, kw_only=True)
class ObsidianGraphOutgoingLinkDiagnostic:
    """Counts and bounded details for outgoing graph edges from one note."""

    parsed_count: int
    resolved_count: int
    unresolved_count: int
    unresolved_targets: tuple[ObsidianGraphUnresolvedTargetDiagnostic, ...] = field(
        default_factory=tuple
    )
    resolved_targets: tuple[ObsidianGraphResolvedTargetDiagnostic, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """Normalize edge detail collections to immutable tuples."""
        self.unresolved_targets = tuple(self.unresolved_targets)
        self.resolved_targets = tuple(self.resolved_targets)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphNoteLinkValidationReport:
    """Stable per-note link validation report for REST and MCP boundaries."""

    selector: ObsidianGraphNoteSelector
    note: ObsidianGraphNoteIndexDiagnostic
    outgoing: ObsidianGraphOutgoingLinkDiagnostic
    projection_status: ObsidianGraphProjectionStatusReport


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianGraphNoteRebuildReport:
    """Focused indexed-edge refresh followed by snapshot projection activation."""

    replace_existing_edges: bool
    validation: ObsidianGraphNoteLinkValidationReport
    projection: ObsidianGraphProjectionRebuildReport


def _selector(
    note_id: str | None,
    path: str | None,
) -> ObsidianGraphNoteSelector:
    """Execute selector.

    Args:
        note_id: Identifier for note.
        path: Path used by this operation.

    Returns:
        ObsidianGraphNoteSelector result produced by selector.
    """
    normalized_note_id = _normalize_note_id(note_id)
    normalized_path = _normalize_path(path)
    if normalized_note_id is None and normalized_path is None:
        raise ObsidianValidationError("note_id or path is required")
    return ObsidianGraphNoteSelector(
        note_id=normalized_note_id,
        path=normalized_path,
    )


def _normalize_note_id(note_id: str | None) -> str | None:
    """Normalize note id.

    Args:
        note_id: Identifier for note.

    Returns:
        Normalized note id.
    """
    if note_id is None:
        return None
    normalized = note_id.strip()
    if not normalized:
        raise ObsidianValidationError("note_id must not be blank")
    return normalized


def _normalize_path(path: str | None) -> str | None:
    """Normalize path.

    Args:
        path: Path used by this operation.

    Returns:
        Normalized path.
    """
    if path is None:
        return None
    normalized = str(safe_relative_path(path.strip()))
    if not normalized:
        raise ObsidianValidationError("path must not be blank")
    return normalized


def _outgoing_diagnostics(
    edges: tuple[ObsidianEdge, ...],
    notes: tuple[ObsidianNote, ...],
    include_resolved_targets: bool,
) -> ObsidianGraphOutgoingLinkDiagnostic:
    """Execute outgoing diagnostics.

    Args:
        edges: Edges used by this operation.
        notes: Notes used by this operation.
        include_resolved_targets: Whether to include resolved targets.

    Returns:
        ObsidianGraphOutgoingLinkDiagnostic result produced by outgoing diagnostics.
    """
    notes_by_id = {note.note_id: note for note in notes}
    notes_by_path = {note.relative_path: note for note in notes}
    healthy_notes = tuple(
        note for note in notes if note.index_status is ObsidianIndexStatus.INDEXED
    )
    healthy_notes_by_id = {note.note_id: note for note in healthy_notes}
    healthy_notes_by_path = {note.relative_path: note for note in healthy_notes}
    healthy_notes_by_link_name = _notes_by_link_name(healthy_notes)
    resolved: list[ObsidianGraphResolvedTargetDiagnostic] = []
    unresolved: list[ObsidianGraphUnresolvedTargetDiagnostic] = []
    for edge in sorted(edges, key=lambda item: item.edge_id):
        target = _resolve_target(
            edge,
            notes_by_id=notes_by_id,
            notes_by_path=notes_by_path,
            healthy_notes_by_id=healthy_notes_by_id,
            healthy_notes_by_path=healthy_notes_by_path,
            healthy_notes_by_link_name=healthy_notes_by_link_name,
        )
        if isinstance(target, ObsidianGraphResolvedTargetDiagnostic):
            resolved.append(target)
        else:
            unresolved.append(target)
    return ObsidianGraphOutgoingLinkDiagnostic(
        parsed_count=len(edges),
        resolved_count=len(resolved),
        unresolved_count=len(unresolved),
        unresolved_targets=tuple(unresolved),
        resolved_targets=tuple(resolved) if include_resolved_targets else (),
    )


def _resolve_target(
    edge: ObsidianEdge,
    notes_by_id: dict[str, ObsidianNote],
    notes_by_path: dict[str, ObsidianNote],
    healthy_notes_by_id: dict[str, ObsidianNote],
    healthy_notes_by_path: dict[str, ObsidianNote],
    healthy_notes_by_link_name: dict[str, tuple[ObsidianNote, ...]],
) -> ObsidianGraphResolvedTargetDiagnostic | ObsidianGraphUnresolvedTargetDiagnostic:
    """Resolve target.

    Args:
        edge: Edge used by this operation.
        notes_by_id: Identifier for notes by.
        notes_by_path: Notes by path used by this operation.
        healthy_notes_by_id: Identifier for healthy notes by.
        healthy_notes_by_path: Healthy notes by path used by this operation.
        healthy_notes_by_link_name: Healthy notes by link name used by this operation.

    Returns:
        Resolved target.
    """
    if edge.target_note_id is not None:
        target = healthy_notes_by_id.get(edge.target_note_id)
        if target is not None:
            return _resolved_target(edge, target)
        unhealthy = notes_by_id.get(edge.target_note_id)
        if unhealthy is not None:
            return _unresolved_target_not_indexed(edge, unhealthy)
        path_candidate = healthy_notes_by_path.get(edge.target_path)
        return ObsidianGraphUnresolvedTargetDiagnostic(
            edge_id=edge.edge_id,
            target_note_id=edge.target_note_id,
            target_path=edge.target_path,
            relation=edge.relation.value,
            source_kind=edge.source_kind.value,
            code="missing_target_note",
            detail="explicit edge target id is absent from the Obsidian index",
            candidate_note_ids=(
                () if path_candidate is None else (path_candidate.note_id,)
            ),
            candidate_paths=(
                () if path_candidate is None else (path_candidate.relative_path,)
            ),
        )
    target = healthy_notes_by_path.get(edge.target_path)
    if target is not None:
        return _resolved_target(edge, target)
    unhealthy = notes_by_path.get(edge.target_path)
    if unhealthy is not None:
        return _unresolved_target_not_indexed(edge, unhealthy)
    candidates = healthy_notes_by_link_name.get(_link_name(edge.target_path), ())
    if len(candidates) == 1:
        return _resolved_target(edge, candidates[0])
    if len(candidates) > 1:
        return ObsidianGraphUnresolvedTargetDiagnostic(
            edge_id=edge.edge_id,
            target_note_id=edge.target_note_id,
            target_path=edge.target_path,
            relation=edge.relation.value,
            source_kind=edge.source_kind.value,
            code="ambiguous_target_note",
            detail="edge target matches multiple healthy Obsidian notes",
            candidate_note_ids=tuple(note.note_id for note in candidates),
            candidate_paths=tuple(note.relative_path for note in candidates),
        )
    return ObsidianGraphUnresolvedTargetDiagnostic(
        edge_id=edge.edge_id,
        target_note_id=edge.target_note_id,
        target_path=edge.target_path,
        relation=edge.relation.value,
        source_kind=edge.source_kind.value,
        code="missing_target_note",
        detail="edge target is absent from the healthy Obsidian index",
    )


def _resolved_target(
    edge: ObsidianEdge,
    target: ObsidianNote,
) -> ObsidianGraphResolvedTargetDiagnostic:
    """Execute resolved target.

    Args:
        edge: Edge used by this operation.
        target: Target used by this operation.

    Returns:
        ObsidianGraphResolvedTargetDiagnostic result produced by resolved target.
    """
    return ObsidianGraphResolvedTargetDiagnostic(
        edge_id=edge.edge_id,
        target_note_id=target.note_id,
        target_path=target.relative_path,
        relation=edge.relation.value,
        source_kind=edge.source_kind.value,
    )


def _unresolved_target_not_indexed(
    edge: ObsidianEdge,
    target: ObsidianNote,
) -> ObsidianGraphUnresolvedTargetDiagnostic:
    """Execute unresolved target not indexed.

    Args:
        edge: Edge used by this operation.
        target: Target used by this operation.

    Returns:
        ObsidianGraphUnresolvedTargetDiagnostic result produced by unresolved target not indexed.
    """
    return ObsidianGraphUnresolvedTargetDiagnostic(
        edge_id=edge.edge_id,
        target_note_id=target.note_id,
        target_path=edge.target_path,
        relation=edge.relation.value,
        source_kind=edge.source_kind.value,
        code="target_not_indexed",
        detail=f"edge target exists with index_status={target.index_status.value}",
        candidate_note_ids=(target.note_id,),
        candidate_paths=(target.relative_path,),
    )


def _notes_by_link_name(
    notes: tuple[ObsidianNote, ...],
) -> dict[str, tuple[ObsidianNote, ...]]:
    """Execute notes by link name.

    Args:
        notes: Notes used by this operation.

    Returns:
        dict[str, tuple[ObsidianNote, ...]] result produced by notes by link name.
    """
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
    """Execute link name.

    Args:
        path: Path used by this operation.

    Returns:
        str result produced by link name.
    """
    return PurePosixPath(path).stem.strip().casefold()
