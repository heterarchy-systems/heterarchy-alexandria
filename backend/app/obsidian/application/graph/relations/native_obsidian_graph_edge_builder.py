"""Native Rust adapter for Obsidian graph edge-candidate compute."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.application.graph.relations.obsidian_graph_edge_compute_contracts import (
    ObsidianGraphEdgeComputeProvider,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_contracts import (
    _FRONTMATTER_RELATIONS,
)
from app.obsidian.application.graph.relations.obsidian_graph_relation_targets import (
    _relation_targets,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianEdgeIndex
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_NATIVE_EXTRACTION_VERSION = 1


class _FrontmatterEdgeWire(TypedDict):
    target_path: str | None
    target_note_id: str | None
    relation: str
    source_field: str


class _ReferenceDocumentWire(TypedDict):
    note_id: str
    relative_path: str
    alexandria_root: str
    body: str
    frontmatter_edges: list[_FrontmatterEdgeWire]


class _ReferenceBatchWire(TypedDict):
    contract_version: int
    extraction_version: int
    documents: list[_ReferenceDocumentWire]


# protocol-contract: structural-seam
class NativeReferenceExtractionModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by graph-edge extraction."""

    def extract_reference_batch_json(self, payload: bytes) -> bytes:
        """Extract references and edge candidates from one strict batch.

        Args:
            payload: Strict native reference-extraction request JSON.

        Returns:
            Strict native reference-extraction result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeObsidianGraphEdgeBuilder(ObsidianGraphEdgeComputeProvider):
    """Keep relation policy in Python and delegate deterministic edge compute to Rust."""

    native_module: NativeReferenceExtractionModule

    def build(
        self,
        note_id: str,
        relative_path: str,
        alexandria_root: str,
        frontmatter: JSONObject,
        body: str,
    ) -> list[ObsidianEdgeIndex]:
        """Return Rust-computed graph edges under Python-owned relation policy.

        Args:
            note_id: Stable source note identity.
            relative_path: Vault-relative source path.
            alexandria_root: Managed Alexandria root, or ``.`` for root-vault installs.
            frontmatter: Parsed JSON-compatible note frontmatter.
            body: Markdown body text.

        Returns:
            Existing ObsidianEdgeIndex DTOs in deterministic legacy order.

        Raises:
            ValueError: If native output violates the reference-extraction wire contract.
        """
        request = _ReferenceBatchWire(
            contract_version=1,
            extraction_version=_NATIVE_EXTRACTION_VERSION,
            documents=[
                _ReferenceDocumentWire(
                    note_id=note_id,
                    relative_path=relative_path,
                    alexandria_root=alexandria_root,
                    body=body,
                    frontmatter_edges=_frontmatter_edge_inputs(frontmatter),
                )
            ],
        )
        encoded = self.native_module.extract_reference_batch_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_edges(loads_json(encoded))


def create_native_obsidian_graph_edge_builder() -> NativeObsidianGraphEdgeBuilder:
    """Create the fail-closed Obsidian edge builder over the shared native module.

    Returns:
        Native graph-edge builder.
    """
    module = cast(NativeReferenceExtractionModule, load_native_compute_module())
    return NativeObsidianGraphEdgeBuilder(module)


def _frontmatter_edge_inputs(frontmatter: JSONObject) -> list[_FrontmatterEdgeWire]:
    """Execute frontmatter edge inputs.

    Args:
        frontmatter: Frontmatter used by this operation.

    Returns:
        list[_FrontmatterEdgeWire] result produced by frontmatter edge inputs.
    """
    edges: list[_FrontmatterEdgeWire] = []
    for field_name, fallback_relation in _FRONTMATTER_RELATIONS:
        if field_name == "source_refs" and "source_ref_links" in frontmatter:
            continue
        for target in _relation_targets(
            frontmatter.get(field_name), field_name=field_name
        ):
            relation = target.relation or fallback_relation
            edges.append(
                _FrontmatterEdgeWire(
                    target_path=target.path,
                    target_note_id=target.note_id,
                    relation=relation.value,
                    source_field=field_name,
                )
            )
    return edges


def _decode_edges(value: JSONValue) -> list[ObsidianEdgeIndex]:
    """Decode edges.

    Args:
        value: Value being processed.

    Returns:
        Decoded edges.
    """
    root = _object(value, "root")
    if (
        root.get("contract_version") != 1
        or root.get("extraction_version") != _NATIVE_EXTRACTION_VERSION
    ):
        raise ValueError(
            "NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: invalid contract version"
        )
    results = _array(root.get("results"), "results")
    if len(results) != 1:
        raise ValueError(
            "NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: expected one document result"
        )
    result = _object(results[0], "result")
    return [_edge(raw_edge) for raw_edge in _array(result.get("edges"), "edges")]


def _edge(value: JSONValue) -> ObsidianEdgeIndex:
    """Execute edge.

    Args:
        value: Value being processed.

    Returns:
        ObsidianEdgeIndex result produced by edge.
    """
    edge = _object(value, "edge")
    edge_id = _required_text(edge, "edge_id")
    source_note_id = _required_text(edge, "source_note_id")
    source_path = _required_text(edge, "source_path")
    target_path = _required_text(edge, "target_path")
    target_note_id = edge.get("target_note_id")
    if target_note_id is not None and not isinstance(target_note_id, str):
        raise ValueError(
            "NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: invalid target note id"
        )
    relation_text = _required_text(edge, "relation")
    source_kind_text = _required_text(edge, "source_kind")
    confidence = edge.get("confidence")
    if not isinstance(confidence, float) or not (
        float("-inf") < confidence < float("inf")
    ):
        raise ValueError("NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: invalid confidence")
    try:
        relation = ObsidianRelationType(relation_text)
        source_kind = ObsidianEdgeSourceKind(source_kind_text)
    except ValueError as exc:
        raise ValueError(
            "NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: invalid relation/source kind"
        ) from exc
    return ObsidianEdgeIndex(
        edge_id=edge_id,
        source_note_id=source_note_id,
        source_path=source_path,
        target_note_id=target_note_id,
        target_path=target_path,
        relation=relation,
        confidence=confidence,
        source_kind=source_kind,
    )


def _required_text(value: JSONObject, key: str) -> str:
    """Execute required text.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by required text.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: invalid {key}")
    return raw


def _object(value: JSONValue | None, field: str) -> JSONObject:
    """Execute object.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        JSONObject result produced by object.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: {field} must be an object"
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
        raise ValueError(
            f"NATIVE_REFERENCE_EXTRACTION_OUTPUT_ERROR: {field} must be an array"
        )
    return value
