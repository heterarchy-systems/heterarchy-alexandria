"""Native Rust adapter for bounded traversal over the active Obsidian graph projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
    ObsidianGraphTraversalRequest,
    ObsidianGraphTraversalResult,
    ObsidianGraphTraversalVisit,
)
from app.obsidian.domain.repositories.obsidian_graph_traversal_compute_provider import (
    IObsidianGraphTraversalComputeProvider,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

_NATIVE_GRAPH_COMPUTE_VERSION = 1
_AUTHORITY = "rust:graph_compute:traversal:v1"


class _ProjectionNodeWire(TypedDict):
    note_id: str
    relative_path: str
    alexandria_type: str
    title: str
    status: str
    project: str | None


class _ProjectionEdgeWire(TypedDict):
    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str
    target_path: str
    relation: str
    confidence: float
    source_kind: str


class _ProjectionWire(TypedDict):
    nodes: list[_ProjectionNodeWire]
    edges: list[_ProjectionEdgeWire]


class _TraversalRequestWire(TypedDict):
    request_id: str
    start_note_id: str
    direction: str
    relations: list[str]
    max_depth: int
    max_results: int


class _TraversalBatchWire(TypedDict):
    contract_version: int
    graph_compute_version: int
    projection: _ProjectionWire
    traversal_requests: list[_TraversalRequestWire]


# protocol-contract: structural-seam
class NativeGraphTraversalModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by active-projection graph traversal."""

    def traverse_graph_projection_json(self, payload: bytes) -> bytes:
        """Traverse an active projection from one strict coarse JSON request.

        Args:
            payload: Strict traversal request payload.

        Returns:
            Strict traversal result payload.
        """


@dataclass(frozen=True, slots=True)
class NativeObsidianGraphTraversalComputeProvider(
    IObsidianGraphTraversalComputeProvider
):
    """Map typed graph snapshots through the authoritative Rust traversal compute."""

    native_module: NativeGraphTraversalModule

    @property
    def authority(self) -> str:
        """Return the deterministic traversal compute authority identifier.

        Returns:
            Stable Rust graph traversal authority identifier.
        """
        return _AUTHORITY

    def traverse(
        self,
        projection: ObsidianGraphProjection,
        requests: tuple[ObsidianGraphTraversalRequest, ...],
    ) -> tuple[ObsidianGraphTraversalResult, ...]:
        """Traverse one active projection in one coarse native call.

        Args:
            projection: Immutable active graph projection loaded by Python.
            requests: Bounded traversal requests in caller order.

        Returns:
            Strict decoded traversal results in the same order.

        Raises:
            ValueError: If native output violates the traversal contract.
        """
        payload = _TraversalBatchWire(
            contract_version=1,
            graph_compute_version=_NATIVE_GRAPH_COMPUTE_VERSION,
            projection=_projection_wire(projection),
            traversal_requests=[_request_wire(request) for request in requests],
        )
        encoded = self.native_module.traverse_graph_projection_json(
            dumps_json(cast(JSONValue, payload))
        )
        return _decode_results(loads_json(encoded), requests)


def create_native_obsidian_graph_traversal_compute_provider() -> (
    IObsidianGraphTraversalComputeProvider
):
    """Create the fail-closed active-projection traversal provider.

    Returns:
        Native Rust graph traversal provider.
    """
    module = cast(NativeGraphTraversalModule, load_native_compute_module())
    return NativeObsidianGraphTraversalComputeProvider(native_module=module)


def _projection_wire(projection: ObsidianGraphProjection) -> _ProjectionWire:
    """Map one active graph projection to the strict native wire.

    Args:
        projection: Active graph projection.

    Returns:
        JSON-compatible typed projection payload.
    """
    return _ProjectionWire(
        nodes=[_node_wire(node) for node in projection.nodes],
        edges=[_edge_wire(edge) for edge in projection.edges],
    )


def _node_wire(node: ObsidianGraphProjectionNode) -> _ProjectionNodeWire:
    """Map one projected node to the native wire.

    Args:
        node: Projected graph node.

    Returns:
        Typed node wire.
    """
    return _ProjectionNodeWire(
        note_id=node.note_id,
        relative_path=node.relative_path,
        alexandria_type=node.alexandria_type.value,
        title=node.title,
        status=node.status,
        project=node.project,
    )


def _edge_wire(edge: ObsidianGraphProjectionEdge) -> _ProjectionEdgeWire:
    """Map one projected edge to the native wire.

    Args:
        edge: Projected graph edge.

    Returns:
        Typed edge wire.

    Raises:
        ValueError: If an active projection edge is missing its resolved target.
    """
    if edge.target_note_id is None:
        raise ValueError("GRAPH_TRAVERSAL_PROJECTION_INVALID: unresolved target edge")
    return _ProjectionEdgeWire(
        edge_id=edge.edge_id,
        source_note_id=edge.source_note_id,
        source_path=edge.source_path,
        target_note_id=edge.target_note_id,
        target_path=edge.target_path,
        relation=edge.relation.value,
        confidence=edge.confidence,
        source_kind=edge.source_kind.value,
    )


def _request_wire(request: ObsidianGraphTraversalRequest) -> _TraversalRequestWire:
    """Map one bounded traversal request to the native wire.

    Args:
        request: Typed traversal request.

    Returns:
        Typed traversal request wire.
    """
    return _TraversalRequestWire(
        request_id=request.request_id,
        start_note_id=request.start_note_id,
        direction=request.direction.value,
        relations=list(request.relations),
        max_depth=request.max_depth,
        max_results=request.max_results,
    )


def _decode_results(
    value: JSONValue,
    requests: tuple[ObsidianGraphTraversalRequest, ...],
) -> tuple[ObsidianGraphTraversalResult, ...]:
    """Decode and validate one native traversal response.

    Args:
        value: Decoded native JSON response.
        requests: Original requests used to validate identity and ordering.

    Returns:
        Strict traversal results.

    Raises:
        ValueError: If the native output shape or identity order is invalid.
    """
    root = _object(value, "root")
    if _integer(root, "contract_version") != 1:
        raise ValueError(
            "NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: contract version mismatch"
        )
    if _integer(root, "graph_compute_version") != _NATIVE_GRAPH_COMPUTE_VERSION:
        raise ValueError("NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: graph version mismatch")
    raw_results = _array(root.get("traversals"), "traversals")
    if len(raw_results) != len(requests):
        raise ValueError("NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: result count mismatch")
    results = tuple(_result(item) for item in raw_results)
    for request, result in zip(requests, results, strict=True):
        if (
            result.request_id != request.request_id
            or result.start_note_id != request.start_note_id
        ):
            raise ValueError(
                "NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: result identity mismatch"
            )
    return results


def _result(value: JSONValue) -> ObsidianGraphTraversalResult:
    """Decode one traversal result.

    Args:
        value: Raw traversal result.

    Returns:
        Strict traversal result.
    """
    raw = _object(value, "traversal")
    return ObsidianGraphTraversalResult(
        request_id=_text(raw, "request_id"),
        start_note_id=_text(raw, "start_note_id"),
        start_found=_boolean(raw, "start_found"),
        visits=tuple(_visit(item) for item in _array(raw.get("visits"), "visits")),
        truncated=_boolean(raw, "truncated"),
    )


def _visit(value: JSONValue) -> ObsidianGraphTraversalVisit:
    """Decode one traversal visit.

    Args:
        value: Raw visit value.

    Returns:
        Strict graph traversal visit.
    """
    raw = _object(value, "visit")
    return ObsidianGraphTraversalVisit(
        note_id=_text(raw, "note_id"),
        depth=_integer(raw, "depth"),
    )


def _object(value: JSONValue, name: str) -> dict[str, JSONValue]:
    """Require one JSON object.

    Args:
        value: Decoded JSON value.
        name: Diagnostic field name.

    Returns:
        String-keyed JSON object.

    Raises:
        ValueError: If the value is not an object.
    """
    if not isinstance(value, dict):
        raise ValueError(f"NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: invalid {name}")
    return value


def _array(value: JSONValue, name: str) -> list[JSONValue]:
    """Require one JSON array.

    Args:
        value: Decoded JSON value.
        name: Diagnostic field name.

    Returns:
        JSON array.

    Raises:
        ValueError: If the value is not an array.
    """
    if not isinstance(value, list):
        raise ValueError(f"NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: invalid {name}")
    return value


def _text(value: dict[str, JSONValue], name: str) -> str:
    """Require one non-empty string field.

    Args:
        value: Parent object.
        name: Field name.

    Returns:
        String value.

    Raises:
        ValueError: If the field is missing or invalid.
    """
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ValueError(f"NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: invalid {name}")
    return item


def _integer(value: dict[str, JSONValue], name: str) -> int:
    """Require one non-negative integer field.

    Args:
        value: Parent object.
        name: Field name.

    Returns:
        Integer value.

    Raises:
        ValueError: If the field is missing or invalid.
    """
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: invalid {name}")
    return item


def _boolean(value: dict[str, JSONValue], name: str) -> bool:
    """Require one boolean field.

    Args:
        value: Parent object.
        name: Field name.

    Returns:
        Boolean value.

    Raises:
        ValueError: If the field is missing or invalid.
    """
    item = value.get(name)
    if not isinstance(item, bool):
        raise ValueError(f"NATIVE_GRAPH_TRAVERSAL_OUTPUT_ERROR: invalid {name}")
    return item
