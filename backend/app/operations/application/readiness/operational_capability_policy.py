"""Classify independently usable Alexandria platform capabilities."""

from __future__ import annotations

from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.operations.domain.entities.operational_capability import (
    OperationalCapability,
    OperationalCapabilitySnapshot,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityState,
)


def capability_snapshot(
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapabilitySnapshot:
    """Separate durable core readiness from optional semantic dependencies.

    Args:
        readiness: Full operational readiness snapshot.

    Returns:
        Independently classified platform capabilities.
    """
    core_blockers = _core_blockers(readiness)
    core_warnings = _core_warnings(readiness)
    core_ready = not core_blockers
    core = OperationalCapability(
        state=(
            OperationalCapabilityState.READY
            if core_ready and not core_warnings
            else (
                OperationalCapabilityState.DEGRADED
                if core_ready
                else OperationalCapabilityState.BLOCKED
            )
        ),
        ready=core_ready,
        blockers=tuple(core_blockers),
        warnings=tuple(core_warnings),
    )

    semantic_blockers = _semantic_blockers(readiness)
    semantic_ready = not semantic_blockers
    semantic = OperationalCapability(
        state=(
            OperationalCapabilityState.READY
            if semantic_ready
            else OperationalCapabilityState.DEGRADED
        ),
        ready=semantic_ready,
        blockers=tuple(semantic_blockers),
        warnings=tuple(readiness.rag.warnings),
    )
    return OperationalCapabilitySnapshot(
        checked_at=readiness.checked_at,
        core_memory=core,
        semantic_retrieval=semantic,
    )


def _core_blockers(readiness: OperationalReadinessSnapshot) -> list[str]:
    """Execute core blockers.

    Args:
        readiness: Readiness used by this operation.

    Returns:
        list[str] result produced by core blockers.
    """
    blockers: list[str] = []
    if not readiness.database.reachable:
        blockers.append("database_unreachable")
    elif readiness.database.integrity != "HEALTHY":
        blockers.append("database_integrity_not_healthy")
    if not readiness.vault.exists:
        blockers.append("vault_not_found")
    elif not readiness.vault.alexandria_root_exists:
        blockers.append("alexandria_root_not_found")
    if readiness.vault.stale_notes:
        blockers.append("obsidian_stale_notes_present")
    if readiness.vault.error_notes:
        blockers.append("obsidian_error_notes_present")
    if readiness.rag.fts is not RagHealthState.HEALTHY:
        blockers.append("rag_fts_not_healthy")
    return blockers


def _core_warnings(readiness: OperationalReadinessSnapshot) -> list[str]:
    """Execute core warnings.

    Args:
        readiness: Readiness used by this operation.

    Returns:
        list[str] result produced by core warnings.
    """
    warnings: list[str] = []
    reconciliation = readiness.reconciliation
    if reconciliation.configured and not reconciliation.reachable:
        warnings.append("memory_reconciliation_repository_unreachable")
    if reconciliation.missing_temporal_states:
        warnings.append("memory_reconciliation_temporal_backfill_required")
    if reconciliation.open_conflicts or reconciliation.reviewing_conflicts:
        warnings.append("memory_reconciliation_review_required")
    return warnings


def _semantic_blockers(readiness: OperationalReadinessSnapshot) -> list[str]:
    """Execute semantic blockers.

    Args:
        readiness: Readiness used by this operation.

    Returns:
        list[str] result produced by semantic blockers.
    """
    blockers: list[str] = []
    if readiness.rag.vector is not RagHealthState.HEALTHY:
        blockers.append("rag_vector_not_healthy")
    if readiness.rag.embedding is not RagHealthState.HEALTHY:
        blockers.append("rag_embedding_not_healthy")
    if readiness.rag.effective_strategy is not RagStrategy.HYBRID:
        blockers.append("rag_default_strategy_not_hybrid")
    if readiness.rag.warnings:
        blockers.append("rag_status_warnings_present")
    return blockers
