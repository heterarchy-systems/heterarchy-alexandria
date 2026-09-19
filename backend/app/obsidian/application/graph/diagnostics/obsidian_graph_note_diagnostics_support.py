"""Obsidian graph note diagnostics support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildReport,
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianEdge, ObsidianNote
from app.obsidian.infrastructure.markdown.paths import (
    safe_relative_path,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianValidationError,
)
from app.shared.infrastructure.native_compile_plan import (
    DiagnosticEdgeWire,
    DiagnosticNoteWire,
    create_native_compile_plan_provider,
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
    """Resolve cached outgoing edges through the Rust graph authority.

    Args:
        edges: Edges used by this operation.
        notes: Notes used by this operation.
        include_resolved_targets: Whether to include resolved targets.

    Returns:
        ObsidianGraphOutgoingLinkDiagnostic result produced by outgoing diagnostics.
    """
    notes_wire: list[DiagnosticNoteWire] = [
        {
            "note_id": note.note_id,
            "relative_path": note.relative_path,
            "title": note.title,
            "status": note.status,
            "index_status": note.index_status.value,
            "aliases": list(_note_aliases(note)),
        }
        for note in notes
    ]
    ordered_edges = tuple(sorted(edges, key=lambda item: item.edge_id))
    edges_wire: list[DiagnosticEdgeWire] = [
        {
            "edge_id": edge.edge_id,
            "source_note_id": edge.source_note_id,
            "target_note_id": edge.target_note_id,
            "target_path": edge.target_path,
        }
        for edge in ordered_edges
    ]
    edges_by_id = {edge.edge_id: edge for edge in ordered_edges}
    provider = create_native_compile_plan_provider()
    resolutions = provider.resolve_note_targets(notes=notes_wire, edges=edges_wire)

    resolved: list[ObsidianGraphResolvedTargetDiagnostic] = []
    unresolved: list[ObsidianGraphUnresolvedTargetDiagnostic] = []
    for resolution in resolutions:
        edge = edges_by_id[resolution["edge_id"]]
        outcome = resolution["outcome"]
        if outcome == "RESOLVED":
            resolved.append(
                ObsidianGraphResolvedTargetDiagnostic(
                    edge_id=edge.edge_id,
                    target_note_id=resolution["target_note_id"] or "",
                    target_path=resolution["target_path"] or edge.target_path,
                    relation=edge.relation.value,
                    source_kind=edge.source_kind.value,
                )
            )
            continue
        if outcome == "TARGET_NOT_INDEXED":
            code: GraphLinkValidationIssueCode = "target_not_indexed"
            detail = (
                "edge target exists with "
                f"index_status={resolution.get('target_index_status')}"
            )
        elif outcome == "AMBIGUOUS":
            code = "ambiguous_target_note"
            detail = "edge target matches multiple healthy Obsidian notes"
        else:
            code = "missing_target_note"
            detail = (
                "explicit edge target id is absent from the Obsidian index"
                if edge.target_note_id is not None
                else "edge target is absent from the healthy Obsidian index"
            )
        unresolved.append(
            ObsidianGraphUnresolvedTargetDiagnostic(
                edge_id=edge.edge_id,
                target_note_id=resolution["target_note_id"] or edge.target_note_id,
                target_path=edge.target_path,
                relation=edge.relation.value,
                source_kind=edge.source_kind.value,
                code=code,
                detail=detail,
                candidate_note_ids=tuple(resolution["candidate_note_ids"]),
                candidate_paths=tuple(resolution["candidate_paths"]),
            )
        )
    return ObsidianGraphOutgoingLinkDiagnostic(
        parsed_count=len(edges),
        resolved_count=len(resolved),
        unresolved_count=len(unresolved),
        unresolved_targets=tuple(unresolved),
        resolved_targets=tuple(resolved) if include_resolved_targets else (),
    )


def _note_aliases(note: ObsidianNote) -> tuple[str, ...]:
    """Decode the alias list used by the graph link-name authority.

    Args:
        note: Note used by this operation.

    Returns:
        Decoded alias tuple.
    """
    aliases = note.frontmatter.get("aliases")
    if isinstance(aliases, str):
        return (aliases,) if aliases.strip() else ()
    if isinstance(aliases, list):
        return tuple(
            alias for alias in aliases if isinstance(alias, str) and alias.strip()
        )
    return ()
