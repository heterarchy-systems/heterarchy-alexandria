"""Operational service factories shared by the application container."""

from __future__ import annotations

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.integration.context_projection_integrity_service import (
    ContextProjectionIntegrityService,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_service import (
    MemoryReconciliationReadinessService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.operations.application.readiness.operational_readiness_cache import (
    OperationalReadinessCache,
)
from app.operations.application.readiness.operational_readiness_service import (
    GraphProjectionReadinessPort,
    OperationalReadinessService,
)
from app.operations.application.readiness.operational_retrieval_canary_service import (
    OperationalRetrievalCanaryService,
)
from app.operations.application.readiness.operational_runtime_provenance_service import (
    OperationalRuntimeProvenanceService,
)
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.database import Database


def create_operational_readiness_service(
    config: AppConfig,
    database: Database,
    context_service: ContextService,
    obsidian_service: ObsidianService,
    reconciliation_service: MemoryReconciliationReadinessService | None,
    readiness_cache: OperationalReadinessCache,
    projection_integrity_service: ContextProjectionIntegrityService,
    runtime_provenance_service: OperationalRuntimeProvenanceService,
    graph_projection_service: GraphProjectionReadinessPort,
) -> OperationalReadinessService:
    """Assemble one request-scoped operational readiness object graph.

    Args:
        config: Validated application configuration.
        database: Shared database lifecycle coordinator.
        context_service: Request-scoped Context application service.
        obsidian_service: Request-scoped canonical Vault application service.
        reconciliation_service: Optional memory reconciliation diagnostics service.
        readiness_cache: Bounded fail-open readiness cache.
        projection_integrity_service: Persisted projection-integrity reader.
        runtime_provenance_service: Application-scoped immutable provenance probe.
        graph_projection_service: Canonical PostgreSQL graph status reader.

    Returns:
        Request-scoped readiness service sharing one Context service with its canary.
    """
    retrieval_canary_service = OperationalRetrievalCanaryService(
        context_service=context_service,
        query=config.readiness_canary_query,
        limit=config.readiness_canary_limit,
    )
    return OperationalReadinessService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        reconciliation_service=reconciliation_service,
        readiness_cache=readiness_cache,
        runtime_provenance_service=runtime_provenance_service,
        retrieval_canary_service=retrieval_canary_service,
        projection_integrity_service=projection_integrity_service,
        graph_projection_service=graph_projection_service,
    )
