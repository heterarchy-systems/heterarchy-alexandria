"""Typed Python adapter for the Rust knowledge compile-plan authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from pydantic import TypeAdapter

from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

COMPILE_PLAN_CONTRACT_VERSION = 1
COMPILE_PLAN_COMPILER_VERSION = 1


class NativeCompilePlanModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by compile planning."""

    def compile_plan_json(self, payload: bytes) -> bytes:
        """Compile one deterministic plan from the strict JSON request.

        Args:
            payload: Strict native compile-plan request JSON.

        Returns:
            Strict native compile-plan result JSON.
        """

    def resolve_note_targets_json(self, payload: bytes) -> bytes:
        """Resolve cached edge targets through the graph resolution authority.

        Args:
            payload: Strict native target-resolution request JSON.

        Returns:
            Strict native resolution result JSON.
        """


class _CompilePolicyWire(TypedDict):
    chunk_max_chars: int
    chunk_overlap_chars: int
    embedding_fingerprint_key: str


class _CompileEdgeSeedWire(TypedDict):
    target_path: str | None
    target_note_id: str | None
    relation: str
    source_field: str


class _CompileContextIdentityWire(TypedDict):
    scope: str | None
    project: str | None
    workspace_id: str | None
    agent_id: str | None
    user_id: str | None
    session_id: str | None
    content_hash: str | None


class _CompileManifestCandidateWire(TypedDict):
    note_id: str
    relative_path: str
    canonical_relative_path: str
    is_context: bool
    identity: _CompileContextIdentityWire
    supersedes_context_id: str | None
    superseded_by_context_id: str | None


class CompileDocumentWire(TypedDict):
    relative_path: str
    note_id: str
    title: str
    alexandria_type: str
    status: str
    aliases: list[str]
    text: str | None
    source_hash: str
    body: str
    frontmatter: JSONValue
    edge_seeds: list[_CompileEdgeSeedWire]
    provided_chunks: list[_CompileProvidedChunkWire] | None
    provided_edges: list[_CompileProvidedEdgeWire] | None
    manifest_candidate: _CompileManifestCandidateWire | None


class _CompileProvidedChunkWire(TypedDict):
    chunk_index: int
    content_hash: str


class _CompileProvidedEdgeWire(TypedDict):
    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str | None
    target_path: str
    relation: str
    confidence: float
    source_kind: str


class _CurrentSourceSnapshotWire(TypedDict):
    documents: list[CompileDocumentWire]


class _PreviousDocumentStateWire(TypedDict):
    note_id: str
    relative_path: str
    source_hash: str
    chunk_hashes: list[str]
    edge_ids: list[str]


class _PreviousCompilationSnapshotWire(TypedDict):
    embedding_fingerprint_key: str
    documents: list[_PreviousDocumentStateWire]


class _CompilePlanRequestWire(TypedDict):
    contract_version: int
    policy: _CompilePolicyWire
    current: _CurrentSourceSnapshotWire
    previous: _PreviousCompilationSnapshotWire


class _EmbeddingDocumentDeltaWire(TypedDict):
    action: str
    reason: str
    chunk_indexes: list[int]


class _CompileChunkPlanWire(TypedDict):
    record: JSONValue
    content_hash: str
    action: str


class CompileEdgePlanWire(TypedDict):
    edge_id: str
    source_note_id: str
    source_path: str
    seed_target_note_id: str | None
    candidate_target_path: str
    relation: str
    confidence: float
    source_kind: str
    action: str
    resolution: str
    target_note_id: str | None


class _CompileDocumentUpsertWire(TypedDict):
    relative_path: str
    note_id: str
    source_hash: str
    title: str
    alexandria_type: str
    frontmatter: JSONValue
    body: str
    action: str
    manifest_accepted: bool
    chunks: list[_CompileChunkPlanWire]
    edges: list[CompileEdgePlanWire]
    removed_edge_ids: list[str]
    embedding: _EmbeddingDocumentDeltaWire


class _CompileDocumentRemovalWire(TypedDict):
    note_id: str
    relative_path: str


class _CompileDiagnosticWire(TypedDict):
    relative_path: str
    context_id: str
    message: str


class CompilePlanResult(TypedDict):
    """Strict decoded native compile-plan result."""

    contract_version: int
    compiler_version: int
    policy_version: str
    upserts: list[_CompileDocumentUpsertWire]
    removals: list[_CompileDocumentRemovalWire]
    diagnostics: list[_CompileDiagnosticWire]
    plan_fingerprint: str


_PLAN_RESULT_ADAPTER: TypeAdapter[CompilePlanResult] = TypeAdapter(CompilePlanResult)


class DiagnosticNoteWire(TypedDict):
    """Strict diagnostic note payload for target resolution."""

    note_id: str
    relative_path: str
    title: str
    status: str
    index_status: str
    aliases: list[str]


class DiagnosticEdgeWire(TypedDict):
    """Strict diagnostic edge payload for target resolution."""

    edge_id: str
    source_note_id: str
    target_note_id: str | None
    target_path: str


class DiagnosticTargetResolution(TypedDict):
    """Strict structured resolution for one cached edge."""

    edge_id: str
    outcome: str
    target_note_id: str | None
    target_path: str | None
    target_index_status: str | None
    candidate_note_ids: list[str]
    candidate_paths: list[str]


class _ResolveTargetsRequestWire(TypedDict):
    contract_version: int
    notes: list[DiagnosticNoteWire]
    edges: list[DiagnosticEdgeWire]


_TARGET_RESOLUTION_ADAPTER: TypeAdapter[list[DiagnosticTargetResolution]] = TypeAdapter(
    list[DiagnosticTargetResolution]
)


@dataclass(frozen=True, slots=True)
class NativeCompilePlanProvider:
    """Compile deterministic knowledge plans through the Rust authority."""

    native_module: NativeCompilePlanModule

    @property
    def authority(self) -> str:
        """Return the deterministic compile authority identifier.

        Returns:
            Stable compute authority identifier.
        """
        return "rust"

    def compile(
        self,
        *,
        policy: _CompilePolicyWire,
        current_documents: list[CompileDocumentWire],
        previous: _PreviousCompilationSnapshotWire,
    ) -> CompilePlanResult:
        """Compile one plan for the submitted snapshots.

        Args:
            policy: Deterministic compile policy.
            current_documents: Analyzed current documents.
            previous: Previous compiled state used as the diff baseline.

        Returns:
            Strict typed compile plan.

        Raises:
            ValueError: If the native output fails the strict wire contract.
        """
        request: _CompilePlanRequestWire = {
            "contract_version": COMPILE_PLAN_CONTRACT_VERSION,
            "policy": policy,
            "current": {"documents": current_documents},
            "previous": previous,
        }
        encoded = self.native_module.compile_plan_json(
            dumps_json(cast(JSONValue, request))
        )
        decoded = loads_json(encoded)
        result = _PLAN_RESULT_ADAPTER.validate_python(decoded)
        _validate_plan_invariants(result)
        return result

    def resolve_note_targets(
        self,
        *,
        notes: list[DiagnosticNoteWire],
        edges: list[DiagnosticEdgeWire],
    ) -> list[DiagnosticTargetResolution]:
        """Resolve cached edge targets through the graph resolution authority.

        Args:
            notes: Strict diagnostic note payloads (id/path/title/status/aliases).
            edges: Strict diagnostic edge payloads.

        Returns:
            One structured resolution per edge, in request order.

        Raises:
            ValueError: If the native output fails the strict wire contract.
        """
        request: _ResolveTargetsRequestWire = {
            "contract_version": COMPILE_PLAN_CONTRACT_VERSION,
            "notes": notes,
            "edges": edges,
        }
        encoded = self.native_module.resolve_note_targets_json(
            dumps_json(cast(JSONValue, request))
        )
        decoded = loads_json(encoded)
        return _TARGET_RESOLUTION_ADAPTER.validate_python(decoded)


def _validate_plan_invariants(result: CompilePlanResult) -> None:
    """Reject native output that violates the compile-plan contract."""
    if result["contract_version"] != COMPILE_PLAN_CONTRACT_VERSION:
        raise ValueError("NATIVE_COMPILE_PLAN_OUTPUT_ERROR: invalid contract version")
    if result["compiler_version"] != COMPILE_PLAN_COMPILER_VERSION:
        raise ValueError("NATIVE_COMPILE_PLAN_OUTPUT_ERROR: invalid compiler version")
    if not result["plan_fingerprint"]:
        raise ValueError("NATIVE_COMPILE_PLAN_OUTPUT_ERROR: missing plan fingerprint")
    upsert_paths = [upsert["relative_path"] for upsert in result["upserts"]]
    if upsert_paths != sorted(upsert_paths):
        raise ValueError("NATIVE_COMPILE_PLAN_OUTPUT_ERROR: unsorted upserts")
    removal_paths = [removal["relative_path"] for removal in result["removals"]]
    if removal_paths != sorted(removal_paths):
        raise ValueError("NATIVE_COMPILE_PLAN_OUTPUT_ERROR: unsorted removals")
    overlap = set(upsert_paths) & set(removal_paths)
    if overlap:
        raise ValueError(
            f"NATIVE_COMPILE_PLAN_OUTPUT_ERROR: path is both upsert and removal: {overlap}"
        )


def create_native_compile_plan_provider() -> NativeCompilePlanProvider:
    """Create the compile-plan provider bound to the native compute module.

    Returns:
        Provider wired to the loaded native extension.

    Raises:
        RuntimeError: If the extension is missing or contract-incompatible.
    """
    module = cast(
        NativeCompilePlanModule,
        load_native_compute_module(),
    )
    return NativeCompilePlanProvider(native_module=module)
