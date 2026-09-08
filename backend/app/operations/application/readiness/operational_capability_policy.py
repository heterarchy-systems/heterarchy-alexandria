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
    OperationalCapabilityFreshness,
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
        freshness=_rag_freshness(readiness.rag.vector, readiness.rag.warnings),
    )
    source = _source_capability(readiness)
    metadata_index = _metadata_index_capability(readiness)
    fts = _rag_capability(readiness.rag.fts, "fts", readiness)
    vector = _rag_capability(readiness.rag.vector, "vector", readiness)
    embedding = _rag_capability(readiness.rag.embedding, "embedding", readiness)
    graph = _graph_capability(readiness)
    reconciliation = _reconciliation_capability(readiness)
    return OperationalCapabilitySnapshot(
        checked_at=readiness.checked_at,
        core_memory=core,
        semantic_retrieval=semantic,
        source=source,
        metadata_index=metadata_index,
        fts=fts,
        vector=vector,
        embedding=embedding,
        graph=graph,
        reconciliation=reconciliation,
    )


def _source_capability(
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapability:
    """Classify canonical source availability independently of index metadata."""
    if not readiness.vault.exists or not readiness.vault.alexandria_root_exists:
        return OperationalCapability(
            state=OperationalCapabilityState.BLOCKED,
            ready=False,
            blockers=("source_unavailable",),
            warnings=(),
        )
    if not readiness.vault.readable:
        return OperationalCapability(
            state=OperationalCapabilityState.BLOCKED,
            ready=False,
            blockers=("source_unreadable",),
            warnings=(),
        )
    return OperationalCapability(
        state=OperationalCapabilityState.READY,
        ready=True,
        blockers=(),
        warnings=(),
    )


def _metadata_index_capability(
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapability:
    """Classify metadata-index evidence without treating unknown as empty."""
    vault = readiness.vault
    if (
        vault.indexed_notes is None
        or vault.stale_notes is None
        or vault.error_notes is None
    ):
        return OperationalCapability(
            state=OperationalCapabilityState.UNKNOWN,
            ready=False,
            blockers=(),
            warnings=("metadata_index_unknown",),
            source_revision=readiness.projection_integrity.current_source_revision,
            projection_revision=readiness.projection_integrity.source_revision,
            freshness=_projection_freshness(readiness),
        )
    blockers: list[str] = []
    warnings: list[str] = []
    if (
        readiness.vault.indexed_notes is None
        or readiness.vault.stale_notes is None
        or readiness.vault.error_notes is None
    ):
        warnings.append("metadata_index_unknown")
    error_notes = vault.error_notes
    stale_notes = vault.stale_notes
    if error_notes is not None and error_notes > 0:
        blockers.append("metadata_index_errors_present")
    if stale_notes is not None and stale_notes > 0:
        warnings.append("metadata_index_stale")
    state = (
        OperationalCapabilityState.BLOCKED
        if blockers
        else OperationalCapabilityState.DEGRADED
        if warnings
        else OperationalCapabilityState.READY
    )
    return OperationalCapability(
        state=state,
        ready=not blockers and not warnings,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        source_revision=readiness.projection_integrity.current_source_revision,
        projection_revision=readiness.projection_integrity.source_revision,
        freshness=_projection_freshness(readiness),
    )


def _rag_capability(
    state: RagHealthState,
    name: str,
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapability:
    """Map one RAG dependency health state to independent evidence."""
    if state is RagHealthState.HEALTHY:
        capability_state = OperationalCapabilityState.READY
        ready = True
        blockers: tuple[str, ...] = ()
        warnings: tuple[str, ...] = ()
        freshness = OperationalCapabilityFreshness.CURRENT
    elif state is RagHealthState.DISABLED:
        capability_state = OperationalCapabilityState.UNKNOWN
        ready = False
        blockers = ()
        warnings = (f"{name}_disabled",)
        freshness = OperationalCapabilityFreshness.UNKNOWN
    elif state is RagHealthState.REINDEX_REQUIRED:
        capability_state = OperationalCapabilityState.DEGRADED
        ready = False
        blockers = ()
        warnings = (f"{name}_stale",)
        freshness = OperationalCapabilityFreshness.STALE
    else:
        capability_state = OperationalCapabilityState.DEGRADED
        ready = False
        blockers = ()
        warnings = (f"{name}_degraded",)
        freshness = OperationalCapabilityFreshness.UNKNOWN
    return OperationalCapability(
        state=capability_state,
        ready=ready,
        blockers=blockers,
        warnings=warnings,
        source_revision=readiness.projection_integrity.current_source_revision,
        projection_revision=readiness.projection_integrity.source_revision,
        freshness=freshness,
    )


def _graph_capability(
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapability:
    """Classify graph projection status without inventing source freshness."""
    graph = readiness.graph
    if graph.status == "ready":
        return OperationalCapability(
            state=OperationalCapabilityState.READY,
            ready=True,
            blockers=(),
            warnings=("graph_projection_freshness_unknown",),
            projection_revision=graph.projection_revision,
            freshness=OperationalCapabilityFreshness.UNKNOWN,
        )
    if graph.status == "unavailable":
        return OperationalCapability(
            state=OperationalCapabilityState.BLOCKED,
            ready=False,
            blockers=("graph_projection_unavailable",),
            warnings=graph.warnings,
            projection_revision=graph.projection_revision,
            freshness=OperationalCapabilityFreshness.UNKNOWN,
        )
    return OperationalCapability(
        state=OperationalCapabilityState.UNKNOWN,
        ready=False,
        blockers=(),
        warnings=graph.warnings or ("graph_projection_unchecked",),
        projection_revision=graph.projection_revision,
        freshness=OperationalCapabilityFreshness.UNKNOWN,
    )


def _reconciliation_capability(
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapability:
    """Classify reconciliation reachability and existing diagnostics."""
    reconciliation = readiness.reconciliation
    if not reconciliation.configured:
        return OperationalCapability(
            state=OperationalCapabilityState.OPTIONAL,
            ready=False,
            blockers=(),
            warnings=("reconciliation_unconfigured",),
        )
    if not reconciliation.reachable:
        return OperationalCapability(
            state=OperationalCapabilityState.BLOCKED,
            ready=False,
            blockers=("reconciliation_unreachable",),
            warnings=(),
        )
    warnings: list[str] = []
    if reconciliation.open_conflicts or reconciliation.reviewing_conflicts:
        warnings.append("reconciliation_review_required")
    if reconciliation.failed_results:
        warnings.append("reconciliation_failures_present")
    return OperationalCapability(
        state=(
            OperationalCapabilityState.DEGRADED
            if warnings
            else OperationalCapabilityState.READY
        ),
        ready=not warnings,
        blockers=(),
        warnings=tuple(warnings),
    )


def _projection_freshness(
    readiness: OperationalReadinessSnapshot,
) -> OperationalCapabilityFreshness:
    """Map existing indexed-source revision evidence to capability freshness."""
    projection = readiness.projection_integrity
    if not projection.checked or not projection.available:
        return OperationalCapabilityFreshness.UNKNOWN
    if (
        projection.stale
        or projection.source_revision != projection.current_source_revision
    ):
        return OperationalCapabilityFreshness.STALE
    return OperationalCapabilityFreshness.CURRENT


def _rag_freshness(
    state: RagHealthState,
    warnings: tuple[str, ...],
) -> OperationalCapabilityFreshness:
    """Return RAG freshness without inferring it from absent evidence."""
    if warnings and state is not RagHealthState.HEALTHY:
        return OperationalCapabilityFreshness.STALE
    if state is RagHealthState.HEALTHY:
        return OperationalCapabilityFreshness.CURRENT
    return OperationalCapabilityFreshness.UNKNOWN


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
    if (
        readiness.vault.indexed_notes is None
        or readiness.vault.stale_notes is None
        or readiness.vault.error_notes is None
    ):
        warnings.append("metadata_index_unknown")
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
