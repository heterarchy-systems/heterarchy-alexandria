"""Native Rust adapter for bounded graph candidate selection over an active projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphCandidatePathHop,
    ObsidianGraphCandidateSelectionResult,
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionNode,
    ObsidianGraphSelectedCandidate,
    ObsidianGraphTitleRelevance,
    ObsidianGraphTraversalRequest,
    ObsidianGraphTraversalResult,
    ObsidianGraphTraversalVisit,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphTraversalDirection,
)
from app.obsidian.domain.repositories.obsidian_graph_candidate_selection_compute_provider import (
    IObsidianGraphCandidateSelectionComputeProvider,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

_NATIVE_GRAPH_COMPUTE_VERSION = 1
_AUTHORITY = "rust:graph_compute:candidate_selection:v1"
_ERROR = "NATIVE_GRAPH_CANDIDATE_SELECTION_OUTPUT_ERROR"


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


class _CandidateSelectionWire(TypedDict):
    contract_version: int
    graph_compute_version: int
    projection: _ProjectionWire
    traversal_requests: list[_TraversalRequestWire]
    primary_note_ids: list[str]
    query: str
    max_candidates: int
    min_shared_trigrams: int


# protocol-contract: structural-seam
class NativeGraphCandidateSelectionModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by graph candidate selection."""

    def select_graph_projection_candidates_json(self, payload: bytes) -> bytes:
        """Select graph candidates from one strict coarse JSON request.

        Args:
            payload: Strict candidate-selection request payload.

        Returns:
            Strict candidate-selection result payload.
        """


@dataclass(frozen=True, slots=True)
class NativeObsidianGraphCandidateSelectionComputeProvider(
    IObsidianGraphCandidateSelectionComputeProvider
):
    """Map active graph snapshots through authoritative Rust candidate selection."""

    native_module: NativeGraphCandidateSelectionModule

    @property
    def authority(self) -> str:
        """Return the deterministic candidate-selection authority identifier.

        Returns:
            Stable Rust graph candidate-selection authority identifier.
        """
        return _AUTHORITY

    def select_candidates(
        self,
        projection: ObsidianGraphProjection,
        requests: tuple[ObsidianGraphTraversalRequest, ...],
        primary_note_ids: tuple[str, ...],
        query: str,
        max_candidates: int,
        min_shared_trigrams: int,
    ) -> ObsidianGraphCandidateSelectionResult:
        """Select a relevance-bounded candidate set in one native call.

        Args:
            projection: Immutable active graph projection loaded by Python.
            requests: Bounded graph traversal requests in caller order.
            primary_note_ids: Existing ranked primary note identities needing title evidence.
            query: Original retrieval query used for title relevance.
            max_candidates: Maximum selected candidate count.
            min_shared_trigrams: Minimum shared query/title trigram count.

        Returns:
            Strict traversal trace and bounded selected candidate identities.

        Raises:
            ValueError: If native output violates the selection contract.
        """
        payload = _CandidateSelectionWire(
            contract_version=1,
            graph_compute_version=_NATIVE_GRAPH_COMPUTE_VERSION,
            projection=_projection_wire(projection),
            traversal_requests=[_request_wire(request) for request in requests],
            primary_note_ids=list(primary_note_ids),
            query=query,
            max_candidates=max_candidates,
            min_shared_trigrams=min_shared_trigrams,
        )
        encoded = self.native_module.select_graph_projection_candidates_json(
            dumps_json(cast(JSONValue, payload))
        )
        return _decode_selection(
            loads_json(encoded),
            projection=projection,
            requests=requests,
            primary_note_ids=primary_note_ids,
            max_candidates=max_candidates,
        )


def create_native_obsidian_graph_candidate_selection_compute_provider() -> (
    NativeObsidianGraphCandidateSelectionComputeProvider
):
    """Create the fail-closed native graph candidate-selection provider.

    Returns:
        Native Rust graph candidate-selection provider.
    """
    module = cast(NativeGraphCandidateSelectionModule, load_native_compute_module())
    return NativeObsidianGraphCandidateSelectionComputeProvider(native_module=module)


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
    """Map one projected node to the strict native wire.

    Args:
        node: Active projection node.

    Returns:
        Typed JSON-compatible native node payload.
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
    """Map one resolved projected edge to the strict native wire.

    Args:
        edge: Active projection edge.

    Returns:
        Typed JSON-compatible native edge payload.

    Raises:
        ValueError: If the active projection contains an unresolved target.
    """
    if edge.target_note_id is None:
        raise ValueError(
            "GRAPH_CANDIDATE_SELECTION_PROJECTION_INVALID: unresolved target edge"
        )
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
    """Map one traversal request to the strict native wire.

    Args:
        request: Typed traversal request.

    Returns:
        Typed JSON-compatible traversal request payload.
    """
    return _TraversalRequestWire(
        request_id=request.request_id,
        start_note_id=request.start_note_id,
        direction=request.direction.value,
        relations=list(request.relations),
        max_depth=request.max_depth,
        max_results=request.max_results,
    )


def _decode_selection(
    value: JSONValue,
    projection: ObsidianGraphProjection,
    requests: tuple[ObsidianGraphTraversalRequest, ...],
    primary_note_ids: tuple[str, ...],
    max_candidates: int,
) -> ObsidianGraphCandidateSelectionResult:
    """Decode and validate one complete native candidate-selection result.

    Args:
        value: Decoded native JSON value.
        projection: Active projection supplied to the native call.
        requests: Traversal requests supplied to the native call.
        primary_note_ids: Primary ids requiring same-call title evidence.
        max_candidates: Requested candidate bound.

    Returns:
        Strict graph traversal, candidate, and primary relevance result.

    Raises:
        ValueError: If any native output invariant or identity check fails.
    """
    root = _object(value, "root")
    if _integer(root, "contract_version") != 1:
        raise ValueError(f"{_ERROR}: contract version mismatch")
    if _integer(root, "graph_compute_version") != _NATIVE_GRAPH_COMPUTE_VERSION:
        raise ValueError(f"{_ERROR}: graph version mismatch")
    traversals = _decode_traversals(root.get("traversals"), requests)
    raw_candidates = _array(root.get("candidates"), "candidates")
    if len(raw_candidates) > max_candidates:
        raise ValueError(f"{_ERROR}: candidate count exceeds requested bound")
    candidates = tuple(_candidate(item) for item in raw_candidates)
    _validate_candidate_identities(candidates, projection, requests)
    primary_title_relevance = tuple(
        _title_relevance(item)
        for item in _array(
            root.get("primary_title_relevance"), "primary_title_relevance"
        )
    )
    if tuple(item.note_id for item in primary_title_relevance) != primary_note_ids:
        raise ValueError(f"{_ERROR}: primary title relevance identity mismatch")
    return ObsidianGraphCandidateSelectionResult(
        traversals=traversals,
        candidates=candidates,
        primary_title_relevance=primary_title_relevance,
    )


def _decode_traversals(
    value: JSONValue,
    requests: tuple[ObsidianGraphTraversalRequest, ...],
) -> tuple[ObsidianGraphTraversalResult, ...]:
    """Decode traversal results and preserve caller request identities.

    Args:
        value: Decoded traversal result array.
        requests: Original traversal requests in caller order.

    Returns:
        Strict traversal results in request order.

    Raises:
        ValueError: If count or request identities differ from the input.
    """
    raw_results = _array(value, "traversals")
    if len(raw_results) != len(requests):
        raise ValueError(f"{_ERROR}: traversal result count mismatch")
    results = tuple(_traversal(item) for item in raw_results)
    for request, result in zip(requests, results, strict=True):
        if (
            result.request_id != request.request_id
            or result.start_note_id != request.start_note_id
        ):
            raise ValueError(f"{_ERROR}: traversal result identity mismatch")
    return results


def _traversal(value: JSONValue) -> ObsidianGraphTraversalResult:
    """Decode one strict graph traversal result.

    Args:
        value: Decoded traversal JSON value.

    Returns:
        Typed graph traversal result.

    Raises:
        ValueError: If any required traversal field has an invalid type.
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
    """Decode one strict traversal visit.

    Args:
        value: Decoded visit JSON value.

    Returns:
        Typed traversal visit.

    Raises:
        ValueError: If note identity or depth is invalid.
    """
    raw = _object(value, "visit")
    return ObsidianGraphTraversalVisit(
        note_id=_text(raw, "note_id"),
        depth=_integer(raw, "depth"),
    )


def _candidate(value: JSONValue) -> ObsidianGraphSelectedCandidate:
    """Decode one selected candidate and validate relevance evidence.

    Args:
        value: Decoded candidate JSON value.

    Returns:
        Typed selected graph candidate.

    Raises:
        ValueError: If graph distance, support, or trigram evidence is invalid.
    """
    raw = _object(value, "candidate")
    union = _integer(raw, "title_trigram_union")
    shared = _integer(raw, "shared_title_trigrams")
    if union == 0 or shared == 0 or shared > union:
        raise ValueError(f"{_ERROR}: invalid trigram evidence")
    seed_support = _integer(raw, "seed_support")
    if seed_support == 0:
        raise ValueError(f"{_ERROR}: seed support must be positive")
    note_id = _text(raw, "note_id")
    min_depth = _integer(raw, "min_depth")
    path_hops = tuple(
        _candidate_path_hop(item)
        for item in _array(raw.get("path_hops"), "candidate path_hops")
    )
    _validate_candidate_path(note_id, min_depth, path_hops)
    return ObsidianGraphSelectedCandidate(
        note_id=note_id,
        min_depth=min_depth,
        seed_support=seed_support,
        shared_title_trigrams=shared,
        title_trigram_union=union,
        path_hops=path_hops,
    )


def _candidate_path_hop(value: JSONValue) -> ObsidianGraphCandidatePathHop:
    """Decode one Rust-owned selected-candidate shortest-path hop.

    Args:
        value: Decoded path-hop JSON value.

    Returns:
        Strict typed path-hop evidence.

    Raises:
        ValueError: If any path-hop field is invalid.
    """
    raw = _object(value, "candidate path hop")
    direction_value = _text(raw, "direction")
    try:
        direction = ObsidianGraphTraversalDirection(direction_value)
    except ValueError as exc:
        raise ValueError(f"{_ERROR}: invalid candidate path direction") from exc
    depth = _integer(raw, "depth")
    if depth < 1:
        raise ValueError(f"{_ERROR}: candidate path depth must be positive")
    source_note_id = _text(raw, "source_note_id")
    target_note_id = _text(raw, "target_note_id")
    if source_note_id == target_note_id:
        raise ValueError(f"{_ERROR}: candidate path hop must change note identity")
    return ObsidianGraphCandidatePathHop(
        edge_id=_text(raw, "edge_id"),
        source_note_id=source_note_id,
        target_note_id=target_note_id,
        relation=_text(raw, "relation"),
        direction=direction,
        depth=depth,
    )


def _validate_candidate_path(
    note_id: str,
    min_depth: int,
    path_hops: tuple[ObsidianGraphCandidatePathHop, ...],
) -> None:
    """Fail closed when Rust candidate path evidence is incomplete or discontinuous.

    Args:
        note_id: Selected candidate note identity.
        min_depth: Rust-selected minimum graph distance.
        path_hops: Rust-owned shortest-path hops.

    Raises:
        ValueError: If path length, depths, continuity, or target identity disagree.
    """
    if min_depth < 1 or len(path_hops) != min_depth:
        raise ValueError(f"{_ERROR}: candidate path length disagrees with min_depth")
    for index, hop in enumerate(path_hops, start=1):
        if hop.depth != index:
            raise ValueError(f"{_ERROR}: candidate path depths are not contiguous")
        if index > 1 and path_hops[index - 2].target_note_id != hop.source_note_id:
            raise ValueError(f"{_ERROR}: candidate path identities are not contiguous")
    if path_hops[-1].target_note_id != note_id:
        raise ValueError(f"{_ERROR}: candidate path target identity mismatch")


def _title_relevance(value: JSONValue) -> ObsidianGraphTitleRelevance:
    """Decode same-call title relevance for one primary note.

    Args:
        value: Decoded title relevance JSON value.

    Returns:
        Typed primary title relevance evidence.

    Raises:
        ValueError: If trigram counts violate bounded relevance invariants.
    """
    raw = _object(value, "title relevance")
    union = _integer(raw, "title_trigram_union")
    shared = _integer(raw, "shared_title_trigrams")
    if union == 0 or shared > union:
        raise ValueError(f"{_ERROR}: invalid title relevance evidence")
    return ObsidianGraphTitleRelevance(
        note_id=_text(raw, "note_id"),
        shared_title_trigrams=shared,
        title_trigram_union=union,
    )


def _validate_candidate_identities(
    candidates: tuple[ObsidianGraphSelectedCandidate, ...],
    projection: ObsidianGraphProjection,
    requests: tuple[ObsidianGraphTraversalRequest, ...],
) -> None:
    """Fail closed on duplicate, external, or seed candidate identities.

    Args:
        candidates: Decoded native selected candidates.
        projection: Active projection used for the native call.
        requests: Traversal requests whose start nodes are protected seeds.

    Raises:
        ValueError: If candidate identities violate the projection contract.
    """
    projected_ids = {node.note_id for node in projection.nodes}
    seed_ids = {request.start_note_id for request in requests}
    candidate_ids = [candidate.note_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(f"{_ERROR}: duplicate candidate identity")
    if any(candidate_id not in projected_ids for candidate_id in candidate_ids):
        raise ValueError(f"{_ERROR}: candidate missing from projection")
    if any(candidate_id in seed_ids for candidate_id in candidate_ids):
        raise ValueError(f"{_ERROR}: seed returned as candidate")


def _object(value: JSONValue, name: str) -> dict[str, JSONValue]:
    """Narrow a decoded JSON value to an object.

    Args:
        value: Decoded JSON value.
        name: Field name used in diagnostics.

    Returns:
        String-keyed JSON object.

    Raises:
        ValueError: If the value is not an object.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{_ERROR}: invalid {name}")
    return value


def _array(value: JSONValue, name: str) -> list[JSONValue]:
    """Narrow a decoded JSON value to an array.

    Args:
        value: Decoded JSON value.
        name: Field name used in diagnostics.

    Returns:
        Decoded JSON array.

    Raises:
        ValueError: If the value is not an array.
    """
    if not isinstance(value, list):
        raise ValueError(f"{_ERROR}: invalid {name}")
    return value


def _text(value: dict[str, JSONValue], name: str) -> str:
    """Read one required non-empty text field.

    Args:
        value: Decoded JSON object.
        name: Required field name.

    Returns:
        Non-empty string field value.

    Raises:
        ValueError: If the field is missing, empty, or not text.
    """
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{_ERROR}: invalid {name}")
    return item


def _integer(value: dict[str, JSONValue], name: str) -> int:
    """Read one required non-negative integer field.

    Args:
        value: Decoded JSON object.
        name: Required field name.

    Returns:
        Non-negative integer field value.

    Raises:
        ValueError: If the field is missing or not a non-negative integer.
    """
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"{_ERROR}: invalid {name}")
    return item


def _boolean(value: dict[str, JSONValue], name: str) -> bool:
    """Read one required boolean field.

    Args:
        value: Decoded JSON object.
        name: Required field name.

    Returns:
        Boolean field value.

    Raises:
        ValueError: If the field is missing or not boolean.
    """
    item = value.get(name)
    if not isinstance(item, bool):
        raise ValueError(f"{_ERROR}: invalid {name}")
    return item
