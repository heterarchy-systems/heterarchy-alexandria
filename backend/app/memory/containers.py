"""Dependency-injector container for memory bounded context."""

from __future__ import annotations

from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.infrastructure.librarians.memory_relation_proposal_provider import (
    ConfiguredMemoryRelationProposalProvider,
)
from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.integration.obsidian_canonical_context_gateway import (
    ObsidianCanonicalContextGateway,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.candidates.context_memory_candidate_recall_source import (
    ContextMemoryCandidateRecallSource,
)
from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.candidates.memory_evolution_candidate_evidence_service import (
    MemoryEvolutionCandidateEvidenceService,
)
from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_service import (
    MemoryCompactReconciliationService,
)
from app.memory.application.reconciliation.conflicts.memory_conflict_service import (
    MemoryConflictService,
)
from app.memory.application.reconciliation.conflicts.memory_temporal_recall_service import (
    MemoryTemporalRecallService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    MemoryReconciliationApplyService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_preview_service import (
    MemoryReconciliationPreviewService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_query_service import (
    MemoryReconciliationQueryService,
)
from app.memory.application.reconciliation.runtime.memory_existing_reconciliation_service import (
    MemoryExistingReconciliationService,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_service import (
    MemoryReconciliationReadinessService,
)
from app.memory.application.reconciliation.runtime.obsidian_memory_canonical_mutation_gateway import (
    ObsidianMemoryCanonicalMutationGateway,
)
from app.memory.application.retrieval.embeddings.embedding_factory import (
    create_embedding_provider,
)
from app.memory.infrastructure.context_embedding_batch_transaction import (
    SqlAlchemyContextEmbeddingBatchTransaction,
)
from app.memory.infrastructure.providers.native_extension_loader import (
    create_native_context_retrieval_kernel_provider,
)
from app.memory.infrastructure.providers.native_memory_reconciliation_candidate_compute_provider import (
    create_native_memory_reconciliation_candidate_compute_provider,
)
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_search_source import (
    SqlAlchemyObsidianContextSearchSource,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.memory.infrastructure.repositories.memory_reconciliation_readiness_repository import (
    SqlAlchemyMemoryReconciliationReadinessRepository,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.infrastructure.markdown.native_context_reindex_manifest import (
    create_native_context_reindex_manifest_validator,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.obsidian.infrastructure.repositories.obsidian_index_repository import (
    SqlAlchemyObsidianIndexRepository,
)
from app.platform.config.app_config import AppConfig
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


class MemoryContainer(containers.DeclarativeContainer):
    """Container for scoped memory/context-vault components."""

    db_session = providers.Dependency(instance_of=AsyncSession)
    app_config = providers.Dependency(instance_of=AppConfig)
    librarian_provider_repo = providers.Dependency()
    provider_secret_repo = providers.Dependency()
    graph_signal_provider = providers.Dependency(default=None)
    graph_candidate_expansion_provider = providers.Dependency(default=None)
    index_maintenance_coordinator = providers.Dependency(
        instance_of=IndexMaintenanceCoordinator
    )
    external_api_rate_limiter = providers.Dependency()
    embedding_provider = providers.Singleton(
        create_embedding_provider,
        vector_enabled=app_config.provided.rag_vector_enabled,
        provider_name=app_config.provided.rag_embedding_provider,
        model_name=app_config.provided.rag_embedding_model,
        dimensions=app_config.provided.rag_embedding_dimensions,
        cache_dir=app_config.provided.rag_embedding_cache_dir,
        threads=app_config.provided.rag_embedding_threads,
    )
    context_repo = providers.Factory(SqlAlchemyContextRepository, session=db_session)
    obsidian_context_search_source = providers.Factory(
        SqlAlchemyObsidianContextSearchSource,
        session=db_session,
    )
    retrieval_kernel_provider = providers.Singleton(
        create_native_context_retrieval_kernel_provider
    )
    context_reindex_manifest_validator = providers.Singleton(
        create_native_context_reindex_manifest_validator,
    )
    context_embedding_batch_transaction = providers.Factory(
        SqlAlchemyContextEmbeddingBatchTransaction,
        session=db_session,
    )
    obsidian_vault_config_store = providers.Singleton(
        ObsidianVaultConfigStore,
        default_vault_path=app_config.provided.obsidian_vault_path,
        default_alexandria_root=app_config.provided.alexandria_obsidian_root,
        config_path=app_config.provided.obsidian_vault_config_path,
    )
    obsidian_index_repo = providers.Factory(
        SqlAlchemyObsidianIndexRepository,
        session=db_session,
    )
    obsidian_service = providers.Factory(
        ObsidianService,
        repository=obsidian_index_repo,
        vault_config_store=obsidian_vault_config_store,
        context_reindex_manifest_validator=context_reindex_manifest_validator,
    )
    canonical_context_gateway = providers.Factory(
        ObsidianCanonicalContextGateway,
        service=obsidian_service,
    )
    memory_compact_repo = providers.Factory(
        ObsidianMemoryCompactRepository,
        vault_path=app_config.provided.obsidian_vault_path,
        relative_dir=app_config.provided.memory_compact_note_dir,
    )
    context_service = providers.Factory(
        ContextService,
        repository=context_repo,
        embedding_provider=embedding_provider,
        vector_retrieval_enabled=app_config.provided.rag_vector_enabled,
        extra_search_sources=providers.List(obsidian_context_search_source),
        canonical_context_repository=canonical_context_gateway,
        graph_signal_provider=graph_signal_provider,
        graph_candidate_expansion_provider=graph_candidate_expansion_provider,
        retrieval_kernel_provider=retrieval_kernel_provider,
        index_maintenance_coordinator=index_maintenance_coordinator,
        embedding_batch_transaction=context_embedding_batch_transaction,
    )
    context_embedding_recovery_service = providers.Singleton(
        ContextEmbeddingRecoveryService,
        batch_size=app_config.provided.rag_embedding_recovery_batch_size,
        max_batches=app_config.provided.rag_embedding_recovery_max_batches,
    )
    memory_compact_service = providers.Factory(
        MemoryCompactService,
        repository=memory_compact_repo,
    )
    reconciliation_readiness_repo = providers.Factory(
        SqlAlchemyMemoryReconciliationReadinessRepository,
        session=db_session,
    )
    reconciliation_repo = providers.Factory(
        SqlAlchemyMemoryReconciliationRepository,
        session=db_session,
    )
    reconciliation_candidate_service = providers.Factory(MemoryCandidateService)
    reconciliation_candidate_compute_provider = providers.Singleton(
        create_native_memory_reconciliation_candidate_compute_provider
    )
    reconciliation_candidate_evidence_service = providers.Factory(
        MemoryEvolutionCandidateEvidenceService,
        provider=reconciliation_candidate_compute_provider,
        embedding_provider=embedding_provider,
    )
    reconciliation_recall_source = providers.Factory(
        ContextMemoryCandidateRecallSource,
        search_service=context_service,
    )
    reconciliation_recall_service = providers.Factory(
        MemoryCandidateRecallService,
        recall_source=reconciliation_recall_source,
        repository=reconciliation_repo,
    )
    reconciliation_model_proposal_provider = providers.Factory(
        ConfiguredMemoryRelationProposalProvider,
        provider_repo=librarian_provider_repo,
        secret_repo=provider_secret_repo,
        provider_id=app_config.provided.memory_reconciliation_provider_id,
        default_model=app_config.provided.memory_reconciliation_model,
        timeout_seconds=(
            app_config.provided.memory_reconciliation_provider_timeout_seconds
        ),
        rate_limiter=external_api_rate_limiter,
    )
    reconciliation_classifier = providers.Factory(
        MemoryRelationClassifier,
        proposal_provider=reconciliation_model_proposal_provider,
    )
    reconciliation_plan_service = providers.Factory(MemoryReconciliationPlanService)
    reconciliation_preview_service = providers.Factory(
        MemoryReconciliationPreviewService,
        candidate_service=reconciliation_candidate_service,
        recall_service=reconciliation_recall_service,
        candidate_evidence_service=reconciliation_candidate_evidence_service,
        classifier=reconciliation_classifier,
        plan_service=reconciliation_plan_service,
        repository=reconciliation_repo,
    )
    reconciliation_canonical_gateway = providers.Factory(
        ObsidianMemoryCanonicalMutationGateway,
        service=obsidian_service,
    )
    reconciliation_apply_service = providers.Factory(
        MemoryReconciliationApplyService,
        repository=reconciliation_repo,
        canonical_gateway=reconciliation_canonical_gateway,
    )
    reconciliation_query_service = providers.Factory(
        MemoryReconciliationQueryService,
        repository=reconciliation_repo,
    )
    memory_temporal_recall_service = providers.Factory(
        MemoryTemporalRecallService,
        context_service=context_service,
        repository=reconciliation_repo,
    )
    memory_compact_reconciliation_policy = providers.Factory(
        MemoryCompactReconciliationPolicy
    )
    memory_compact_reconciliation_service = providers.Factory(
        MemoryCompactReconciliationService,
        temporal_recall_service=memory_temporal_recall_service,
        policy=memory_compact_reconciliation_policy,
    )
    memory_existing_reconciliation_service = providers.Factory(
        MemoryExistingReconciliationService,
        context_service=context_service,
        candidate_service=reconciliation_candidate_service,
        recall_service=reconciliation_recall_service,
        classifier=reconciliation_classifier,
        plan_service=reconciliation_plan_service,
        repository=reconciliation_repo,
    )
    memory_reconciliation_readiness_service = providers.Factory(
        MemoryReconciliationReadinessService,
        repository=reconciliation_readiness_repo,
        context_service=context_service,
    )
    memory_conflict_service = providers.Factory(
        MemoryConflictService,
        repository=reconciliation_repo,
    )
