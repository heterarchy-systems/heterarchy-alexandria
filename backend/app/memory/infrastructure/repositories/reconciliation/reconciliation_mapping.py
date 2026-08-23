"""Map reconciliation SQL rows through validated storage payloads."""

from __future__ import annotations

from app.memory.domain.entities.memory_reconciliation import (
    MemoryConflictSet,
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
    MemoryRelationRecord,
    MemoryTemporalState,
)
from app.memory.infrastructure.models.reconciliation_models import (
    ContextTemporalStateORM,
    MemoryConflictSetORM,
    MemoryReconciliationPlanORM,
    MemoryReconciliationResultORM,
    MemoryRelationORM,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    conflict_from_payload,
    plan_from_payload,
    relation_from_payload,
    result_from_payload,
    temporal_from_payload,
)
from app.shared.types.extra_types import JSONObject, JSONValue


def plan_from_row(row: MemoryReconciliationPlanORM) -> MemoryReconciliationPlan:
    """Map one reconciliation plan row into its domain entity.

    Args:
        row: Row.

    Returns:
        MemoryReconciliationPlan: Operation result.
    """
    return plan_from_payload(_json_object(row.payload))


def result_from_row(row: MemoryReconciliationResultORM) -> MemoryReconciliationResult:
    """Map one reconciliation result row into its domain entity.

    Args:
        row: Row.

    Returns:
        MemoryReconciliationResult: Operation result.
    """
    return result_from_payload(_json_object(row.payload))


def relation_from_row(row: MemoryRelationORM) -> MemoryRelationRecord:
    """Map one memory relation row into its domain entity.

    Args:
        row: Row.

    Returns:
        MemoryRelationRecord: Operation result.
    """
    return relation_from_payload(_json_object(row.payload))


def conflict_from_row(row: MemoryConflictSetORM) -> MemoryConflictSet:
    """Map one conflict row into its domain entity.

    Args:
        row: Row.

    Returns:
        MemoryConflictSet: Operation result.
    """
    return conflict_from_payload(_json_object(row.payload))


def temporal_from_row(row: ContextTemporalStateORM) -> MemoryTemporalState:
    """Map one temporal overlay row into its domain entity.

    Args:
        row: Row.

    Returns:
        MemoryTemporalState: Operation result.
    """
    return temporal_from_payload(_json_object(row.payload))


def _json_object(value: dict[str, JSONValue]) -> JSONObject:
    """Execute json object.

    Args:
        value: Value being processed.

    Returns:
        JSONObject result produced by json object.
    """
    return dict(value)
