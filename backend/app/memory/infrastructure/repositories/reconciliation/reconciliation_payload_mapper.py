"""Pydantic-validated JSON boundary for reconciliation persistence."""

from __future__ import annotations

from typing import cast

from pydantic import TypeAdapter

from app.memory.domain.entities.memory_reconciliation import (
    MemoryConflictSet,
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
    MemoryRelationRecord,
    MemoryTemporalState,
)
from app.shared.types.extra_types import JSONObject

_PLAN_ADAPTER = TypeAdapter(MemoryReconciliationPlan)
_RESULT_ADAPTER = TypeAdapter(MemoryReconciliationResult)
_RELATION_ADAPTER = TypeAdapter(MemoryRelationRecord)
_CONFLICT_ADAPTER = TypeAdapter(MemoryConflictSet)
_TEMPORAL_ADAPTER = TypeAdapter(MemoryTemporalState)


def plan_payload(value: MemoryReconciliationPlan) -> JSONObject:
    """Serialize a reconciliation plan to a validated JSON object.

    Args:
        value: Value.

    Returns:
        JSONObject: Operation result.
    """
    return _dump(_PLAN_ADAPTER, value)


def plan_from_payload(payload: JSONObject) -> MemoryReconciliationPlan:
    """Validate and restore a reconciliation plan from storage JSON.

    Args:
        payload: Payload.

    Returns:
        MemoryReconciliationPlan: Operation result.
    """
    return _PLAN_ADAPTER.validate_python(payload)


def result_payload(value: MemoryReconciliationResult) -> JSONObject:
    """Serialize a reconciliation result to a validated JSON object.

    Args:
        value: Value.

    Returns:
        JSONObject: Operation result.
    """
    return _dump(_RESULT_ADAPTER, value)


def result_from_payload(payload: JSONObject) -> MemoryReconciliationResult:
    """Validate and restore a reconciliation result from storage JSON.

    Args:
        payload: Payload.

    Returns:
        MemoryReconciliationResult: Operation result.
    """
    return _RESULT_ADAPTER.validate_python(payload)


def relation_payload(value: MemoryRelationRecord) -> JSONObject:
    """Serialize a memory relation to a validated JSON object.

    Args:
        value: Value.

    Returns:
        JSONObject: Operation result.
    """
    return _dump(_RELATION_ADAPTER, value)


def relation_from_payload(payload: JSONObject) -> MemoryRelationRecord:
    """Validate and restore a memory relation from storage JSON.

    Args:
        payload: Payload.

    Returns:
        MemoryRelationRecord: Operation result.
    """
    return _RELATION_ADAPTER.validate_python(payload)


def conflict_payload(value: MemoryConflictSet) -> JSONObject:
    """Serialize a conflict set to a validated JSON object.

    Args:
        value: Value.

    Returns:
        JSONObject: Operation result.
    """
    return _dump(_CONFLICT_ADAPTER, value)


def conflict_from_payload(payload: JSONObject) -> MemoryConflictSet:
    """Validate and restore a conflict set from storage JSON.

    Args:
        payload: Payload.

    Returns:
        MemoryConflictSet: Operation result.
    """
    return _CONFLICT_ADAPTER.validate_python(payload)


def temporal_payload(value: MemoryTemporalState) -> JSONObject:
    """Serialize a temporal overlay to a validated JSON object.

    Args:
        value: Value.

    Returns:
        JSONObject: Operation result.
    """
    return _dump(_TEMPORAL_ADAPTER, value)


def temporal_from_payload(payload: JSONObject) -> MemoryTemporalState:
    """Validate and restore a temporal overlay from storage JSON.

    Args:
        payload: Payload.

    Returns:
        MemoryTemporalState: Operation result.
    """
    return _TEMPORAL_ADAPTER.validate_python(payload)


def _dump[PayloadT](
    adapter: TypeAdapter[PayloadT],
    value: PayloadT,
) -> JSONObject:
    """Execute dump.

    Args:
        adapter: Adapter used by this operation.
        value: Value being processed.

    Returns:
        JSONObject result produced by dump.
    """
    payload = adapter.dump_python(value, mode="json")
    if not isinstance(payload, dict):
        raise TypeError("Reconciliation storage payload must be a JSON object")
    return cast(JSONObject, payload)
