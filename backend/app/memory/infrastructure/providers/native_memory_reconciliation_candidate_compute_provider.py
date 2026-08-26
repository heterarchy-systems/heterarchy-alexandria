"""Native Rust adapter for bulk memory reconciliation candidate discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypedDict, cast

from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateCluster,
    ReconciliationCandidateComputeItem,
    ReconciliationCandidateComputeMetrics,
    ReconciliationCandidateComputePolicy,
    ReconciliationCandidateComputeResult,
    ReconciliationCandidateEvidence,
    ReconciliationExactDuplicateGroup,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_candidate_compute_provider import (
    IMemoryReconciliationCandidateComputeProvider,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_NATIVE_CANDIDATE_VERSION = 1
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _PolicyWire(TypedDict):
    vector_similarity_threshold: float
    graph_similarity_threshold: float
    max_block_size: int
    max_candidates_per_item: int


class _ItemWire(TypedDict):
    item_id: str
    content_hash: str | None
    embedding: list[float] | None
    valid_from_micros: int | None
    valid_to_micros: int | None
    blocking_keys: list[str]
    graph_neighbors: list[str]
    lineage_ancestors: list[str]


class _EnvelopeWire(TypedDict):
    contract_version: int
    candidate_version: int
    policy: _PolicyWire
    items: list[_ItemWire]


# protocol-contract: structural-seam
class NativeReconciliationCandidateModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by candidate discovery."""

    def compute_reconciliation_candidates_json(self, payload: bytes) -> bytes:
        """Compute one strict candidate-discovery request.

        Args:
            payload: Strict native candidate request JSON.

        Returns:
            Strict native candidate result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeMemoryReconciliationCandidateComputeProvider(
    IMemoryReconciliationCandidateComputeProvider
):
    """Delegate bounded candidate discovery to Rust without moving final policy."""

    native_module: NativeReconciliationCandidateModule

    @property
    def authority(self) -> str:
        """Return the active Rust reconciliation-candidate compute authority.

        Returns:
            Stable identifier for the Rust reconciliation-candidate authority.
        """
        return "rust:reconciliation_candidates:v1"

    def discover(
        self,
        items: tuple[ReconciliationCandidateComputeItem, ...],
        policy: ReconciliationCandidateComputePolicy,
    ) -> ReconciliationCandidateComputeResult:
        """Return typed Rust-computed candidate evidence.

        Args:
            items: Typed items selected by the Python application boundary.
            policy: Explicit comparison thresholds and cardinality limits.

        Returns:
            Existing Python-domain candidate evidence DTOs.

        Raises:
            ValueError: If native output violates the candidate wire contract.
        """
        request = _EnvelopeWire(
            contract_version=1,
            candidate_version=_NATIVE_CANDIDATE_VERSION,
            policy=_policy_wire(policy),
            items=[_item_wire(item) for item in items],
        )
        encoded = self.native_module.compute_reconciliation_candidates_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_result(loads_json(encoded))


def create_native_memory_reconciliation_candidate_compute_provider() -> (
    NativeMemoryReconciliationCandidateComputeProvider
):
    """Create the fail-closed candidate provider over the shared native module.

    Returns:
        Native reconciliation candidate compute provider.
    """
    module = cast(NativeReconciliationCandidateModule, load_native_compute_module())
    return NativeMemoryReconciliationCandidateComputeProvider(module)


def _policy_wire(policy: ReconciliationCandidateComputePolicy) -> _PolicyWire:
    """Execute policy wire.

    Args:
        policy: Policy used by this operation.

    Returns:
        _PolicyWire result produced by policy wire.
    """
    return _PolicyWire(
        vector_similarity_threshold=policy.vector_similarity_threshold,
        graph_similarity_threshold=policy.graph_similarity_threshold,
        max_block_size=policy.max_block_size,
        max_candidates_per_item=policy.max_candidates_per_item,
    )


def _item_wire(item: ReconciliationCandidateComputeItem) -> _ItemWire:
    """Execute item wire.

    Args:
        item: Item being processed.

    Returns:
        _ItemWire result produced by item wire.
    """
    return _ItemWire(
        item_id=item.item_id,
        content_hash=item.content_hash,
        embedding=None if item.embedding is None else list(item.embedding),
        valid_from_micros=_epoch_micros(item.valid_from),
        valid_to_micros=_epoch_micros(item.valid_to),
        blocking_keys=list(item.blocking_keys),
        graph_neighbors=list(item.graph_neighbors),
        lineage_ancestors=list(item.lineage_ancestors),
    )


def _epoch_micros(value: datetime | None) -> int | None:
    """Execute epoch micros.

    Args:
        value: Value being processed.

    Returns:
        int | None result produced by epoch micros.
    """
    if value is None:
        return None
    normalized = value.astimezone(UTC)
    delta = normalized - _EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _decode_result(value: JSONValue) -> ReconciliationCandidateComputeResult:
    """Decode result.

    Args:
        value: Value being processed.

    Returns:
        Decoded result.
    """
    root = _object(value, "root")
    if (
        root.get("contract_version") != 1
        or root.get("candidate_version") != _NATIVE_CANDIDATE_VERSION
    ):
        raise ValueError(
            "NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: invalid version"
        )
    duplicate_groups = tuple(
        ReconciliationExactDuplicateGroup(
            content_hash=_text(group, "content_hash"),
            item_ids=tuple(_string_array(group.get("item_ids"), "item_ids")),
        )
        for group in (
            _object(item, "duplicate group")
            for item in _array(
                root.get("exact_duplicate_groups"), "exact_duplicate_groups"
            )
        )
    )
    candidate_pairs = tuple(
        _candidate_pair(_object(item, "candidate pair"))
        for item in _array(root.get("candidate_pairs"), "candidate_pairs")
    )
    clusters = tuple(
        ReconciliationCandidateCluster(
            cluster_index=_int(cluster, "cluster_index"),
            item_ids=tuple(_string_array(cluster.get("item_ids"), "item_ids")),
        )
        for cluster in (
            _object(item, "cluster")
            for item in _array(root.get("clusters"), "clusters")
        )
    )
    metrics = _metrics(_object(root.get("metrics"), "metrics"))
    return ReconciliationCandidateComputeResult(
        exact_duplicate_groups=duplicate_groups,
        candidate_pairs=candidate_pairs,
        clusters=clusters,
        metrics=metrics,
    )


def _candidate_pair(value: JSONObject) -> ReconciliationCandidateEvidence:
    """Execute candidate pair.

    Args:
        value: Value being processed.

    Returns:
        ReconciliationCandidateEvidence result produced by candidate pair.
    """
    vector_similarity = value.get("vector_similarity")
    if vector_similarity is not None:
        vector_similarity = _number(vector_similarity, "vector_similarity")
    temporal_overlap = value.get("temporal_overlap")
    exact_content_hash = value.get("exact_content_hash")
    if not isinstance(temporal_overlap, bool) or not isinstance(
        exact_content_hash, bool
    ):
        raise ValueError(
            "NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: invalid boolean evidence"
        )
    return ReconciliationCandidateEvidence(
        left_id=_text(value, "left_id"),
        right_id=_text(value, "right_id"),
        exact_content_hash=exact_content_hash,
        vector_similarity=vector_similarity,
        temporal_overlap=temporal_overlap,
        graph_similarity=_number(value.get("graph_similarity"), "graph_similarity"),
        lineage=_text(value, "lineage"),
        candidate_score=_number(value.get("candidate_score"), "candidate_score"),
        reasons=tuple(_string_array(value.get("reasons"), "reasons")),
    )


def _metrics(value: JSONObject) -> ReconciliationCandidateComputeMetrics:
    """Execute metrics.

    Args:
        value: Value being processed.

    Returns:
        ReconciliationCandidateComputeMetrics result produced by metrics.
    """
    return ReconciliationCandidateComputeMetrics(
        input_items=_int(value, "input_items"),
        comparison_pairs=_int(value, "comparison_pairs"),
        qualifying_pairs=_int(value, "qualifying_pairs"),
        retained_pairs=_int(value, "retained_pairs"),
        exact_duplicate_groups=_int(value, "exact_duplicate_groups"),
    )


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
            f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: {field} must be an object"
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
            f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: {field} must be an array"
        )
    return value


def _string_array(value: JSONValue | None, field: str) -> list[str]:
    """Execute string array.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        list[str] result produced by string array.
    """
    values = _array(value, field)
    if not all(isinstance(item, str) for item in values):
        raise ValueError(
            f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: invalid {field}"
        )
    return cast(list[str], values)


def _text(value: JSONObject, key: str) -> str:
    """Execute text.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by text.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: invalid {key}")
    return raw


def _int(value: JSONObject, key: str) -> int:
    """Execute int.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        int result produced by int.
    """
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: invalid {key}")
    return raw


def _number(value: JSONValue | None, field: str) -> float:
    """Execute number.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        float result produced by number.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(
            f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: invalid {field}"
        )
    result = float(value)
    if not (float("-inf") < result < float("inf")):
        raise ValueError(
            f"NATIVE_RECONCILIATION_CANDIDATE_OUTPUT_ERROR: non-finite {field}"
        )
    return result
