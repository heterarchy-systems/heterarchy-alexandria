"""Application service for Context Vault linting and retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.memory.application.contexts.embedding.context_embedding_reindex_service import (
    ContextEmbeddingBatchTransaction,
)
from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.contexts.linting.context_lint_service import (
    ContextLintService,
)
from app.memory.application.contexts.records.context_record_lifecycle_service import (
    ContextRecordLifecycleService,
)
from app.memory.application.contexts.records.context_record_query_service import (
    ContextRecordQueryService,
)
from app.memory.application.contexts.records.context_search_service import (
    ContextSearchService,
)
from app.memory.application.contexts.records.context_service_lint_mixin import (
    ContextServiceLintMixin,
)
from app.memory.application.contexts.records.context_soft_rebuild_service import (
    ContextSoftRebuildService,
)
from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextPack,
    ContextRecord,
    ContextReindexResult,
    ContextSoftRebuildResult,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import (
    ContextAccessActorType,
    ContextAccessMethod,
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)
from app.memory.domain.repositories.contexts.canonical_context_repository import (
    ICanonicalContextRepository,
)
from app.memory.domain.repositories.contexts.context_graph_signal_provider import (
    IContextGraphSignalProvider,
)
from app.memory.domain.repositories.contexts.context_repository import (
    IContextRepository,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


class ContextService(ContextServiceLintMixin):
    """Stable Context application facade over focused use-case services.

    The facade intentionally retains the public Context API surface used by HTTP,
    MCP, operations, and tests. Validation, record routing, lifecycle mutations,
    recall strategy, embedding lifecycle, and soft rebuild reporting are delegated
    to focused collaborators.
    """

    def __init__(
        self,
        repository: IContextRepository,
        embedding_provider: EmbeddingProvider | None = None,
        vector_retrieval_enabled: bool = False,
        extra_search_sources: Sequence[IContextSearchSource] | None = None,
        canonical_context_repository: ICanonicalContextRepository | None = None,
        graph_signal_provider: IContextGraphSignalProvider | None = None,
        index_maintenance_coordinator: IndexMaintenanceCoordinator | None = None,
        embedding_batch_transaction: ContextEmbeddingBatchTransaction | None = None,
    ) -> None:
        """Initialize service dependencies.

        Args:
            repository: Context persistence port.
            embedding_provider: Optional local embedding provider.
            vector_retrieval_enabled: Whether vector indexing and query paths are wired.
            extra_search_sources: Optional additional Context RAG sources.
            canonical_context_repository: Optional canonical Markdown context adapter.
            graph_signal_provider: Optional score-preserving graph evidence provider.
            embedding_batch_transaction: Optional transaction boundary per reindex batch.
        """
        search_sources = [repository, *(extra_search_sources or ())]
        self._index_maintenance_coordinator = (
            index_maintenance_coordinator or IndexMaintenanceCoordinator()
        )
        self._lint_service = ContextLintService()
        self._embedding_service = ContextEmbeddingService(
            provider=embedding_provider,
            vector_retrieval_enabled=vector_retrieval_enabled,
            search_sources=search_sources,
            batch_transaction=embedding_batch_transaction,
        )
        self._search_service = ContextSearchService(
            search_sources=search_sources,
            embedding_service=self._embedding_service,
            graph_signal_provider=graph_signal_provider,
        )
        self._soft_rebuild_service = ContextSoftRebuildService(
            embedding_service=self._embedding_service,
            search_service=self._search_service,
        )
        self._record_query_service = ContextRecordQueryService(
            repository=repository,
            canonical_repository=canonical_context_repository,
        )
        self._record_lifecycle_service = ContextRecordLifecycleService(
            repository=repository,
            canonical_repository=canonical_context_repository,
        )

    async def get(self, context_id: str) -> ContextRecord:
        """Return one Context or raise not-found.

        Args:
            context_id: Context identifier.

        Returns:
            Stored Context read model.
        """
        return await self._record_query_service.get(context_id)

    async def list_contexts(
        self,
        limit: int = 50,
        offset: int = 0,
        kind: ContextKind | None = None,
        project: str | None = None,
        scope: ContextScope | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_agent: str | None = None,
        tag: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        include_archived: bool = False,
    ) -> tuple[list[ContextRecord], int]:
        """List Contexts with filters.

        Args:
            limit: Maximum returned entries.
            offset: Pagination offset.
            kind: Optional Context kind filter.
            project: Optional project filter.
            scope: Optional scope filter.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            source_agent: Optional source-agent filter.
            tag: Optional tag filter.
            created_after: Optional inclusive created-at lower bound.
            created_before: Optional inclusive created-at upper bound.
            updated_after: Optional inclusive updated-at lower bound.
            updated_before: Optional inclusive updated-at upper bound.
            include_archived: Whether archived entries are included.

        Returns:
            Matching Context rows and total count before pagination.
        """
        return await self._record_query_service.list_contexts(
            limit=limit,
            offset=offset,
            kind=kind,
            project=project,
            scope=scope,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            source_agent=source_agent,
            tag=tag,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            include_archived=include_archived,
        )

    async def chunks(self, context_id: str) -> list[ContextChunkRecord]:
        """Return chunks for one Context.

        Args:
            context_id: Context identifier.

        Returns:
            Stored chunks for the Context.
        """
        return await self._record_query_service.chunks(context_id)

    async def archive(self, context_id: str) -> ContextRecord:
        """Archive one Context.

        Args:
            context_id: Context identifier.

        Returns:
            Archived Context read model.
        """
        return await self._record_lifecycle_service.archive(context_id)

    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> tuple[ContextRecord, ContextRecord]:
        """Link one canonical Context to an existing canonical replacement.

        Args:
            context_id: Source-qualified Context identifier to supersede.
            replacement_context_id: Source-qualified replacement Context identifier.

        Returns:
            Superseded and replacement canonical Context read models.
        """
        return await self._record_lifecycle_service.supersede(
            context_id,
            replacement_context_id,
        )

    async def delete(self, context_id: str) -> None:
        """Hard-delete one SQL-backed Context.

        Args:
            context_id: Context identifier.
        """
        await self._record_lifecycle_service.delete(context_id)

    async def access(
        self,
        context_id: str,
        actor_name: str = "Alexandria UI",
        actor_type: ContextAccessActorType = ContextAccessActorType.UI,
        access_method: ContextAccessMethod = ContextAccessMethod.DETAIL_VIEW,
        source_surface: str | None = "context-detail",
    ) -> ContextRecord:
        """Record an access event.

        Args:
            context_id: Context identifier.
            actor_name: Actor label to store with the access event.
            actor_type: Actor category.
            access_method: Access method category.
            source_surface: Optional UI or tool surface that caused access.

        Returns:
            Updated Context read model.
        """
        return await self._record_lifecycle_service.record_access(
            context_id,
            actor_name=actor_name,
            actor_type=actor_type,
            access_method=access_method,
            source_surface=source_surface,
        )

    async def access_events(
        self,
        context_id: str,
        limit: int = 5,
    ) -> list[ContextAccessEventRecord]:
        """Return recent access events for one Context.

        Args:
            context_id: Context identifier.
            limit: Maximum events to return.

        Returns:
            Recent access events ordered newest first.
        """
        return await self._record_query_service.access_events(
            context_id,
            limit=limit,
        )

    def rag_health(self) -> RagDependencyHealth:
        """Return current RAG dependency health.

        Returns:
            Health state for FTS, vector, and embedding dependencies.
        """
        return self._embedding_service.health()

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        """Return RAG health including persisted embedding fingerprint status.

        Returns:
            Health state that marks vector recall unavailable on mismatch.
        """
        return await self._embedding_service.health_with_index_status()

    async def search(
        self,
        query: str,
        strategy: RagStrategy = RagStrategy.HYBRID,
        limit: int = 5,
        project: str | None = None,
        kind: ContextKind | None = None,
        include_scopes: list[ContextScope] | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None = None,
    ) -> ContextPack:
        """Return a Context pack for one query.

        Args:
            query: Search query text.
            strategy: Requested retrieval strategy.
            limit: Maximum matches.
            project: Optional project filter.
            kind: Optional Context kind filter.
            include_scopes: Optional recall scope filters.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            include_lifecycle_statuses: Optional administrative lifecycle filter.

        Returns:
            Context pack containing retrieved matches and warnings.
        """
        return await self._search_service.search(
            query=query,
            strategy=strategy,
            limit=limit,
            project=project,
            kind=kind,
            include_scopes=include_scopes,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            include_lifecycle_statuses=include_lifecycle_statuses,
        )

    async def reindex_embeddings(
        self,
        limit: int = 100,
        force: bool = False,
    ) -> ContextReindexResult:
        """Backfill or rebuild embeddings for stored context chunks.

        Args:
            limit: Maximum chunks to reindex in this batch.
            force: Whether matching embeddings should be rebuilt.

        Returns:
            Context embedding reindex result.
        """
        async with self._index_maintenance_coordinator.operation("embedding_reindex"):
            return await self._embedding_service.reindex(limit=limit, force=force)

    async def soft_rebuild_embeddings(
        self,
        limit: int = 100,
        verification_query: str | None = None,
        project: str | None = None,
    ) -> ContextSoftRebuildResult:
        """Rebuild embeddings without deleting source Context or note records.

        Args:
            limit: Maximum chunks to rebuild in this batch.
            verification_query: Optional query to run after the rebuild.
            project: Optional project filter for the verification query.

        Returns:
            Operator-facing soft rebuild report.
        """
        async with self._index_maintenance_coordinator.operation(
            "embedding_soft_rebuild"
        ):
            return await self._soft_rebuild_service.rebuild(
                limit=limit,
                verification_query=verification_query,
                project=project,
            )

    async def embedding_source_statuses(self) -> list[ContextEmbeddingSourceStatus]:
        """Return source-level embedding fingerprint diagnostics.

        Returns:
            One status object per configured Context RAG source.
        """
        return await self._embedding_service.source_statuses()
