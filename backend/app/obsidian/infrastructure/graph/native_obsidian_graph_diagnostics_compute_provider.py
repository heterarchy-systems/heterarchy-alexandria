"""Rust-backed graph orphan census and relation suggestion provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.domain.contracts.obsidian_graph_diagnostics_contracts import (
    ObsidianGraphDiagnosticEdge,
    ObsidianGraphDiagnosticNote,
    ObsidianGraphDiagnosticsResult,
    ObsidianGraphOrphanDiagnostic,
    ObsidianGraphOrphanDiagnosticRequest,
    ObsidianGraphSuggestionDiagnostic,
    ObsidianGraphSuggestionDiagnosticRequest,
)
from app.obsidian.domain.repositories.obsidian_graph_diagnostics_compute_provider import (
    IObsidianGraphDiagnosticsComputeProvider,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_GRAPH_COMPUTE_VERSION = 1
_ERROR = "NATIVE_GRAPH_DIAGNOSTICS_OUTPUT_ERROR"


class _DiagnosticNoteWire(TypedDict):
    note_id: str
    relative_path: str
    title: str
    project: str | None
    tags: list[str]


class _DiagnosticEdgeWire(TypedDict):
    edge_id: str
    source_note_id: str
    target_note_id: str | None
    relation: str
    source_kind: str


class _DiagnosticWire(TypedDict):
    contract_version: int
    graph_compute_version: int
    notes: list[_DiagnosticNoteWire]
    edges: list[_DiagnosticEdgeWire]
    orphan_census: JSONObject | None
    relation_suggestions: JSONObject | None


# protocol-contract: structural-seam
class NativeGraphDiagnosticsModule(NativeComputeContractModule, Protocol):
    """Native extension surface for graph diagnostics."""

    def compute_graph_diagnostics_json(self, payload: bytes) -> bytes:
        """Compute one strict graph diagnostics request."""


@dataclass(frozen=True, slots=True)
class NativeObsidianGraphDiagnosticsComputeProvider(
    IObsidianGraphDiagnosticsComputeProvider
):
    """Map typed Python graph rows through the Rust diagnostics kernel."""

    native_module: NativeGraphDiagnosticsModule

    def compute(
        self,
        notes: tuple[ObsidianGraphDiagnosticNote, ...],
        edges: tuple[ObsidianGraphDiagnosticEdge, ...],
        orphan_request: ObsidianGraphOrphanDiagnosticRequest | None,
        suggestion_request: ObsidianGraphSuggestionDiagnosticRequest | None,
    ) -> ObsidianGraphDiagnosticsResult:
        """Compute bounded orphan and relation diagnostics."""
        payload = _DiagnosticWire(
            contract_version=1,
            graph_compute_version=_GRAPH_COMPUTE_VERSION,
            notes=[
                _DiagnosticNoteWire(
                    note_id=note.note_id,
                    relative_path=note.relative_path,
                    title=note.title,
                    project=note.project,
                    tags=list(note.tags),
                )
                for note in notes
            ],
            edges=[
                _DiagnosticEdgeWire(
                    edge_id=edge.edge_id,
                    source_note_id=edge.source_note_id,
                    target_note_id=edge.target_note_id,
                    relation=edge.relation,
                    source_kind=edge.source_kind,
                )
                for edge in edges
            ],
            orphan_census=(
                None
                if orphan_request is None
                else cast(
                    JSONObject,
                    {
                        "project": orphan_request.project,
                        "cursor": orphan_request.cursor,
                        "limit": orphan_request.limit,
                    },
                )
            ),
            relation_suggestions=(
                None
                if suggestion_request is None
                else cast(
                    JSONObject,
                    {
                        "seed_note_id": suggestion_request.seed_note_id,
                        "limit": suggestion_request.limit,
                    },
                )
            ),
        )
        encoded = self.native_module.compute_graph_diagnostics_json(
            dumps_json(cast(JSONValue, payload))
        )
        return _decode_result(loads_json(encoded))


def create_native_obsidian_graph_diagnostics_compute_provider() -> (
    NativeObsidianGraphDiagnosticsComputeProvider
):
    """Create the fail-closed native diagnostics provider."""
    module = cast(NativeGraphDiagnosticsModule, load_native_compute_module())
    return NativeObsidianGraphDiagnosticsComputeProvider(module)


def _decode_result(value: JSONValue) -> ObsidianGraphDiagnosticsResult:
    root = _object(value)
    if _integer(root, "contract_version") != 1:
        raise ValueError(f"{_ERROR}: contract version mismatch")
    if _integer(root, "graph_compute_version") != _GRAPH_COMPUTE_VERSION:
        raise ValueError(f"{_ERROR}: graph compute version mismatch")
    return ObsidianGraphDiagnosticsResult(
        contract_version=1,
        graph_compute_version=_GRAPH_COMPUTE_VERSION,
        orphans=tuple(_orphan(item) for item in _array(root.get("orphans"), "orphans")),
        total_orphans=_integer(root, "total_orphans"),
        next_cursor=_optional_text(root.get("next_cursor")),
        suggestions=tuple(
            _suggestion(item) for item in _array(root.get("suggestions"), "suggestions")
        ),
    )


def _orphan(value: JSONValue) -> ObsidianGraphOrphanDiagnostic:
    raw = _object(value)
    return ObsidianGraphOrphanDiagnostic(
        note_id=_text(raw, "note_id"),
        relative_path=_text(raw, "relative_path"),
        title=_text(raw, "title"),
        project=_optional_text(raw.get("project")),
        in_degree=_integer(raw, "in_degree"),
        out_degree=_integer(raw, "out_degree"),
        canonical_parent_count=_integer(raw, "canonical_parent_count"),
        has_wikilink_connectivity=_boolean(raw, "has_wikilink_connectivity"),
        debt_kinds=tuple(_string_array(raw.get("debt_kinds"), "debt_kinds")),
    )


def _suggestion(value: JSONValue) -> ObsidianGraphSuggestionDiagnostic:
    raw = _object(value)
    confidence = raw.get("confidence")
    if not isinstance(confidence, (float, int)) or isinstance(confidence, bool):
        raise ValueError(f"{_ERROR}: invalid confidence")
    return ObsidianGraphSuggestionDiagnostic(
        candidate_note_id=_text(raw, "candidate_note_id"),
        candidate_path=_text(raw, "candidate_path"),
        candidate_title=_text(raw, "candidate_title"),
        relation=_text(raw, "relation"),
        confidence=float(confidence),
        shared_tags=tuple(_string_array(raw.get("shared_tags"), "shared_tags")),
        shared_neighbor_count=_integer(raw, "shared_neighbor_count"),
        title_overlap_tokens=tuple(
            _string_array(raw.get("title_overlap_tokens"), "title_overlap_tokens")
        ),
        explanation=_text(raw, "explanation"),
    )


def _object(value: JSONValue) -> JSONObject:
    if not isinstance(value, dict):
        raise ValueError(f"{_ERROR}: expected object")
    return value


def _array(value: JSONValue | None, field: str) -> list[JSONValue]:
    if not isinstance(value, list):
        raise ValueError(f"{_ERROR}: {field} must be an array")
    return value


def _string_array(value: JSONValue | None, field: str) -> list[str]:
    values = _array(value, field)
    if not all(isinstance(item, str) for item in values):
        raise ValueError(f"{_ERROR}: {field} contains non-text value")
    return cast(list[str], values)


def _text(value: JSONObject, field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{_ERROR}: {field} must be non-empty text")
    return item


def _optional_text(value: JSONValue | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{_ERROR}: optional text has invalid type")
    return value


def _integer(value: JSONObject, field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{_ERROR}: {field} must be integer")
    return item


def _boolean(value: JSONObject, field: str) -> bool:
    item = value.get(field)
    if not isinstance(item, bool):
        raise ValueError(f"{_ERROR}: {field} must be boolean")
    return item
