"""Operator-facing soft Context embedding rebuild orchestration."""

from __future__ import annotations

from app.memory.application.contexts.embedding.context_embedding_service import (
    ContextEmbeddingService,
)
from app.memory.application.contexts.records.context_search_service import (
    ContextSearchService,
)
from app.memory.domain.entities.context_read_models import ContextSoftRebuildResult
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy


class ContextSoftRebuildService:
    """Rebuild embedding metadata while preserving canonical source records."""

    def __init__(
        self,
        embedding_service: ContextEmbeddingService,
        search_service: ContextSearchService,
    ) -> None:
        """Create the soft rebuild service.

        Args:
            embedding_service: Embedding health and reindex collaborator.
            search_service: Context verification search collaborator.
        """
        self._embedding_service = embedding_service
        self._search_service = search_service

    async def rebuild(
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
        before = await self._embedding_service.health_with_index_status()
        source_status_before = await self._embedding_service.source_statuses()
        reindex = await self._embedding_service.reindex(limit=limit, force=True)
        after = await self._embedding_service.health_with_index_status()
        source_status_after = await self._embedding_service.source_statuses()
        verification_context_ids: tuple[str, ...] = ()
        verification_warnings: tuple[str, ...] = ()
        if verification_query is not None and verification_query.strip():
            verification = await self._search_service.search(
                query=verification_query,
                strategy=RagStrategy.HYBRID,
                limit=min(limit, 10),
                project=project,
            )
            verification_context_ids = tuple(
                dict.fromkeys(match.context.id for match in verification.matches)
            )
            verification_warnings = verification.warnings
        warnings = list(reindex.warnings)
        if after.embedding is RagHealthState.REINDEX_REQUIRED:
            warnings.append(
                "Soft rebuild batch incomplete; rerun with a higher limit or repeat "
                "until after.embedding is HEALTHY."
            )
        return ContextSoftRebuildResult(
            mode="soft_embedding_vector_rebuild",
            source_preservation=(
                "Source contexts, Obsidian notes, and memory records are preserved; "
                "only chunk embedding metadata/vector fields are rewritten."
            ),
            hard_delete_performed=False,
            before=before,
            source_status_before=tuple(source_status_before),
            reindex=reindex,
            after=after,
            source_status_after=tuple(source_status_after),
            verification_query=verification_query,
            verification_matches=len(verification_context_ids),
            verification_context_ids=verification_context_ids,
            verification_warnings=verification_warnings,
            warnings=tuple(warnings),
        )
