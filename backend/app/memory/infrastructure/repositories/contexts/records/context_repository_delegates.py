"""Focused delegation mixins for the SQLAlchemy Context repository facade."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.contracts.context_contracts import (
    ContextAccessCreate,
    ContextChunkEmbeddingUpdate,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    RagHealthState,
)
from app.memory.infrastructure.repositories.contexts.embeddings.context_embedding_store import (
    ContextEmbeddingStore,
)
from app.memory.infrastructure.repositories.contexts.records.context_record_mutation_store import (
    ContextRecordMutationStore,
)
from app.memory.infrastructure.repositories.contexts.records.context_record_query_store import (
    ContextRecordQueryStore,
)
from app.memory.infrastructure.repositories.contexts.search.context_search_store import (
    ContextSearchStore,
)
from app.shared.types.extra_types import JSONObject


class ContextRecordQueryRepositoryDelegate:
    """Delegate Context record and access-history reads."""

    _query_store: ContextRecordQueryStore

    async def get(self, context_id: str) -> ContextRecord | None:
        """Return one non-deleted Context by id.

        Args:
            context_id: Context identifier.

        Returns:
            Stored Context read model when found.
        """
        return await self._query_store.get(context_id)

    async def list_all(
        self,
        limit: int,
        offset: int,
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
        """List Contexts with filters and total count.

        Args:
            limit: Maximum returned entries.
            offset: Pagination offset.
            kind: Optional Context kind filter.
            project: Optional project filter.
            scope: Optional Context scope filter.
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
        return await self._query_store.list_all(
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
        return await self._query_store.chunks(context_id)

    async def access_events(
        self,
        context_id: str,
        limit: int = 5,
    ) -> list[ContextAccessEventRecord]:
        """List recent access events for one Context.

        Args:
            context_id: Context identifier.
            limit: Maximum events to return.

        Returns:
            Recent access events ordered newest first.
        """
        return await self._query_store.access_events(
            context_id=context_id,
            limit=limit,
        )


class ContextRecordMutationRepositoryDelegate:
    """Delegate Context lifecycle and access mutations."""

    _mutation_store: ContextRecordMutationStore

    async def archive(self, context_id: str) -> ContextRecord:
        """Archive one Context instead of deleting it.

        Args:
            context_id: Context identifier.

        Returns:
            Archived Context read model.
        """
        return await self._mutation_store.archive(context_id)

    async def delete(self, context_id: str) -> None:
        """Hard delete one Context and dependent rows.

        Args:
            context_id: Context identifier.
        """
        await self._mutation_store.delete(context_id)

    async def record_access(self, payload: ContextAccessCreate) -> ContextRecord:
        """Record an access event for recall and audit purposes.

        Args:
            payload: Context access event fields.

        Returns:
            Updated Context read model.
        """
        return await self._mutation_store.record_access(payload)


class ContextSearchRepositoryDelegate:
    """Delegate Context FTS and vector candidate search."""

    _search_store: ContextSearchStore

    async def search_fts(
        self,
        recall: ContextFtsRecall,
    ) -> list[ContextSearchMatch]:
        """Search Context chunks with PostgreSQL full-text search.

        Args:
            recall: Validated FTS query and recall filters.

        Returns:
            Ranked Context matches.
        """
        return await self._search_store.search_fts(recall)

    async def search_vector(
        self,
        recall: ContextVectorRecall,
    ) -> list[ContextSearchMatch]:
        """Search Context chunks with stored embeddings.

        Args:
            recall: Validated vector query and recall filters.

        Returns:
            Ranked vector matches.
        """
        return await self._search_store.search_vector(recall)


class ContextEmbeddingRepositoryDelegate:
    """Delegate Context embedding index diagnostics and updates."""

    _embedding_store: ContextEmbeddingStore

    async def chunks_missing_embeddings(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        limit: int,
        force: bool = False,
    ) -> list[ContextChunkRecord]:
        """Return chunks needing embedding backfill or forced rebuild.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.
            limit: Maximum chunks to scan.
            force: Whether matching embeddings may be rebuilt.

        Returns:
            Chunks that require embedding work.
        """
        return await self._embedding_store.chunks_missing_embeddings(
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
            limit=limit,
            force=force,
        )

    async def embedding_index_status(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
    ) -> RagHealthState:
        """Return whether stored embeddings match the current fingerprint.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.

        Returns:
            Embedding index health state.
        """
        return await self._embedding_store.embedding_index_status(
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
        )

    async def embedding_source_status(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        """Return source-level embedding fingerprint diagnostics.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.
            current_fingerprint: Current timestamp-free fingerprint payload.

        Returns:
            Context source embedding status.
        """
        return await self._embedding_store.embedding_source_status(
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
            current_fingerprint=current_fingerprint,
        )

    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        """Persist Context chunk embedding updates.

        Args:
            updates: Embedding updates keyed by chunk identifier.

        Returns:
            Number of chunks updated.
        """
        return await self._embedding_store.update_chunk_embeddings(updates)
