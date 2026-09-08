"""Typed wire boundary for Rust-owned related-note and evidence computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast

from pydantic import TypeAdapter

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
    ObsidianGraphProjection,
    ObsidianGraphRelatedNote,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)


# protocol-contract: structural-seam
class NativeGraphReadModule(NativeComputeContractModule, Protocol):
    """Coarse graph read operation supplied by the required native extension."""

    def read_graph_projection_json(self, payload: bytes) -> bytes:
        """Return ordered graph read results for a typed projection request."""


@dataclass(frozen=True, slots=True)
class _ReadRequest:
    contract_version: Literal[1]
    graph_compute_version: Literal[1]
    projection: ObsidianGraphProjection
    related_note_id: str | None
    limit: int
    evidence_note_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ReadResult:
    contract_version: Literal[1]
    graph_compute_version: Literal[1]
    related_notes: tuple[ObsidianGraphRelatedNote, ...]
    context_evidence: tuple[ObsidianGraphContextEvidence, ...]


_REQUEST_ADAPTER = TypeAdapter(_ReadRequest)
_RESULT_ADAPTER = TypeAdapter(_ReadResult)


def related_notes(
    projection: ObsidianGraphProjection,
    note_id: str,
    limit: int,
) -> tuple[ObsidianGraphRelatedNote, ...]:
    """Decode Rust-selected and ordered one-hop related notes."""
    return _read(projection, note_id, limit, ()).related_notes


def context_evidence(
    projection: ObsidianGraphProjection,
    note_ids: tuple[str, ...],
) -> tuple[ObsidianGraphContextEvidence, ...]:
    """Decode Rust-filtered and classified recalled-edge evidence."""
    return _read(projection, None, 1, note_ids).context_evidence


def _read(
    projection: ObsidianGraphProjection,
    related_note_id: str | None,
    limit: int,
    evidence_note_ids: tuple[str, ...],
) -> _ReadResult:
    module = cast(NativeGraphReadModule, load_native_compute_module())
    payload = _REQUEST_ADAPTER.dump_json(
        _ReadRequest(1, 1, projection, related_note_id, limit, evidence_note_ids)
    )
    return _RESULT_ADAPTER.validate_json(
        module.read_graph_projection_json(payload), strict=True
    )
