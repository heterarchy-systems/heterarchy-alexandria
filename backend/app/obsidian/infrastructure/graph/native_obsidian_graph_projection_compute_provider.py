"""Native Rust adapter for deterministic Obsidian graph projection compute."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

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
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphProjectionIssueCode,
)
from app.obsidian.domain.repositories.obsidian_graph_projection_compute_provider import (
    IObsidianGraphProjectionComputeProvider,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

_NATIVE_GRAPH_COMPUTE_VERSION = 1


class _GraphSourceNoteWire(TypedDict):
    note_id: str
    relative_path: str
    alexandria_type: str
    title: str
    status: str
    project: str | None
    aliases: list[str]
    index_status: str


class _GraphSourceEdgeWire(TypedDict):
    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str | None
    target_path: str
    relation: str
    confidence: float
    source_kind: str


class _GraphComputeWire(TypedDict):
    contract_version: int
    graph_compute_version: int
    batch_size: int
    source_notes: list[_GraphSourceNoteWire]
    source_edges: list[_GraphSourceEdgeWire]
    traversal_requests: list[JSONValue]
    lineage_requests: list[JSONValue]
    previous_projection: None


# protocol-contract: structural-seam
class NativeGraphComputeModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by graph projection compute."""

    def compute_graph_json(self, payload: bytes) -> bytes:
        """Compute one strict graph projection request.

        Args:
            payload: Strict native graph compute request JSON.

        Returns:
            Strict graph compute result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeObsidianGraphProjectionComputeProvider(
    IObsidianGraphProjectionComputeProvider
):
    """Map typed relational-index rows through the native graph compute core."""

    native_module: NativeGraphComputeModule

    def compute(
        self,
        notes: tuple[ObsidianNote, ...],
        edges: tuple[ObsidianEdge, ...],
        batch_size: int,
    ) -> ObsidianGraphProjectionSourceSnapshot:
        """Return the native-computed projection in the existing source snapshot DTO.

        Args:
            notes: Typed note rows loaded by the Python repository boundary.
            edges: Typed edge rows loaded by the Python repository boundary.
            batch_size: Maximum nodes and edges per projection write batch.

        Returns:
            Existing immutable projection source snapshot.

        Raises:
            ValueError: If the native result violates the graph compute wire contract.
        """
        request = _GraphComputeWire(
            contract_version=1,
            graph_compute_version=_NATIVE_GRAPH_COMPUTE_VERSION,
            batch_size=batch_size,
            source_notes=[_note_wire(note) for note in notes],
            source_edges=[_edge_wire(edge) for edge in edges],
            traversal_requests=[],
            lineage_requests=[],
            previous_projection=None,
        )
        encoded = self.native_module.compute_graph_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_snapshot(loads_json(encoded))


def create_native_obsidian_graph_projection_compute_provider() -> (
    NativeObsidianGraphProjectionComputeProvider
):
    """Create the fail-closed graph compute provider over the shared native module.

    Returns:
        Native graph projection compute provider.
    """
    module = cast(NativeGraphComputeModule, load_native_compute_module())
    return NativeObsidianGraphProjectionComputeProvider(module)


def _note_wire(note: ObsidianNote) -> _GraphSourceNoteWire:
    """Execute note wire.

    Args:
        note: Note used by this operation.

    Returns:
        _GraphSourceNoteWire result produced by note wire.
    """
    return _GraphSourceNoteWire(
        note_id=note.note_id,
        relative_path=note.relative_path,
        alexandria_type=note.alexandria_type.value,
        title=note.title,
        status=note.status,
        project=note.project,
        aliases=_aliases(note),
        index_status=note.index_status.value,
    )


def _aliases(note: ObsidianNote) -> list[str]:
    """Execute aliases.

    Args:
        note: Note used by this operation.

    Returns:
        list[str] result produced by aliases.
    """
    value = note.frontmatter.get("aliases")
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        return [
            alias.strip() for alias in value if isinstance(alias, str) and alias.strip()
        ]
    return []


def _edge_wire(edge: ObsidianEdge) -> _GraphSourceEdgeWire:
    """Execute edge wire.

    Args:
        edge: Edge used by this operation.

    Returns:
        _GraphSourceEdgeWire result produced by edge wire.
    """
    return _GraphSourceEdgeWire(
        edge_id=edge.edge_id,
        source_note_id=edge.source_note_id,
        source_path=edge.source_path,
        target_note_id=edge.target_note_id,
        target_path=edge.target_path,
        relation=edge.relation.value,
        confidence=edge.confidence,
        source_kind=edge.source_kind.value,
    )


def _decode_snapshot(value: JSONValue) -> ObsidianGraphProjectionSourceSnapshot:
    """Decode snapshot.

    Args:
        value: Value being processed.

    Returns:
        Decoded snapshot.
    """
    root = _object(value, "root")
    projection = _projection(_object(root.get("projection"), "projection"))
    batches = tuple(
        _batch(raw_batch) for raw_batch in _array(root.get("batches"), "batches")
    )
    issues = tuple(
        _issue(raw_issue) for raw_issue in _array(root.get("issues"), "issues")
    )
    metrics = _metrics(_object(root.get("metrics"), "metrics"))
    return ObsidianGraphProjectionSourceSnapshot(
        projection=projection,
        batches=batches,
        issues=issues,
        metrics=metrics,
    )


def _projection(value: dict[str, JSONValue]) -> ObsidianGraphProjection:
    """Execute projection.

    Args:
        value: Value being processed.

    Returns:
        ObsidianGraphProjection result produced by projection.
    """
    nodes = tuple(_node(item) for item in _array(value.get("nodes"), "nodes"))
    edges = tuple(_projected_edge(item) for item in _array(value.get("edges"), "edges"))
    return ObsidianGraphProjection(nodes=nodes, edges=edges)


def _node(value: JSONValue) -> ObsidianGraphProjectionNode:
    """Execute node.

    Args:
        value: Value being processed.

    Returns:
        ObsidianGraphProjectionNode result produced by node.
    """
    node = _object(value, "node")
    project = node.get("project")
    if project is not None and not isinstance(project, str):
        raise ValueError("NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid project")
    try:
        alexandria_type = AlexandriaNoteType(_text(node, "alexandria_type"))
    except ValueError as exc:
        raise ValueError(
            "NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid alexandria type"
        ) from exc
    return ObsidianGraphProjectionNode(
        note_id=_text(node, "note_id"),
        relative_path=_text(node, "relative_path"),
        alexandria_type=alexandria_type,
        title=_text(node, "title"),
        status=_text(node, "status"),
        project=project,
    )


def _projected_edge(value: JSONValue) -> ObsidianGraphProjectionEdge:
    """Execute projected edge.

    Args:
        value: Value being processed.

    Returns:
        ObsidianGraphProjectionEdge result produced by projected edge.
    """
    edge = _object(value, "edge")
    try:
        relation = ObsidianRelationType(_text(edge, "relation"))
        source_kind = ObsidianEdgeSourceKind(_text(edge, "source_kind"))
    except ValueError as exc:
        raise ValueError(
            "NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid edge enum"
        ) from exc
    confidence = _float(edge, "confidence")
    return ObsidianGraphProjectionEdge(
        edge_id=_text(edge, "edge_id"),
        source_note_id=_text(edge, "source_note_id"),
        source_path=_text(edge, "source_path"),
        target_note_id=_text(edge, "target_note_id"),
        target_path=_text(edge, "target_path"),
        relation=relation,
        confidence=confidence,
        source_kind=source_kind,
    )


def _batch(value: JSONValue) -> ObsidianGraphProjectionBatch:
    """Execute batch.

    Args:
        value: Value being processed.

    Returns:
        ObsidianGraphProjectionBatch result produced by batch.
    """
    batch = _object(value, "batch")
    batch_index = _int(batch, "batch_index")
    return ObsidianGraphProjectionBatch(
        batch_index=batch_index,
        projection=_projection(_object(batch.get("projection"), "batch projection")),
    )


def _issue(value: JSONValue) -> ObsidianGraphProjectionIssue:
    """Execute issue.

    Args:
        value: Value being processed.

    Returns:
        ObsidianGraphProjectionIssue result produced by issue.
    """
    issue = _object(value, "issue")
    try:
        code = ObsidianGraphProjectionIssueCode(_text(issue, "code"))
    except ValueError as exc:
        raise ValueError(
            "NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid issue code"
        ) from exc
    note_id = _optional_text(issue, "note_id")
    edge_id = _optional_text(issue, "edge_id")
    detail = _optional_text(issue, "detail")
    return ObsidianGraphProjectionIssue(
        code=code,
        relative_path=_text(issue, "relative_path"),
        note_id=note_id,
        edge_id=edge_id,
        detail=detail,
    )


def _metrics(value: dict[str, JSONValue]) -> ObsidianGraphProjectionSourceMetrics:
    """Execute metrics.

    Args:
        value: Value being processed.

    Returns:
        ObsidianGraphProjectionSourceMetrics result produced by metrics.
    """
    return ObsidianGraphProjectionSourceMetrics(
        scanned=_int(value, "scanned"),
        indexed=_int(value, "indexed"),
        skipped=_int(value, "skipped"),
        errors=_int(value, "errors"),
    )


def _text(value: dict[str, JSONValue], key: str) -> str:
    """Execute text.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by text.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid {key}")
    return raw


def _optional_text(value: dict[str, JSONValue], key: str) -> str | None:
    """Execute optional text.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str | None result produced by optional text.
    """
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid {key}")
    return raw


def _int(value: dict[str, JSONValue], key: str) -> int:
    """Execute int.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        int result produced by int.
    """
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid {key}")
    return raw


def _float(value: dict[str, JSONValue], key: str) -> float:
    """Execute float.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        float result produced by float.
    """
    raw = value.get(key)
    if not isinstance(raw, float) or not (float("-inf") < raw < float("inf")):
        raise ValueError(f"NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: invalid {key}")
    return raw


def _object(value: JSONValue | None, field: str) -> dict[str, JSONValue]:
    """Execute object.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        dict[str, JSONValue] result produced by object.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: {field} must be an object"
        )
    return value


def _array(value: JSONValue | None, field: str) -> list[JSONValue]:
    """Execute array.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        list[JSONValue] result produced by array.
    """
    if not isinstance(value, list):
        raise ValueError(f"NATIVE_GRAPH_COMPUTE_OUTPUT_ERROR: {field} must be an array")
    return value
