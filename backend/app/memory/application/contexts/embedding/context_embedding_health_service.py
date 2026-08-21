"""Embedding dependency health and persisted fingerprint diagnostics."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.application.retrieval.rag_health import build_rag_dependency_health
from app.memory.domain.entities.context_read_models import (
    ContextEmbeddingSourceStatus,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from sqlalchemy.exc import SQLAlchemyError


class ContextEmbeddingHealthService:
    """Evaluate embedding dependencies and source fingerprint consistency."""

    def __init__(
        self,
        provider: EmbeddingProvider | None,
        vector_retrieval_enabled: bool,
        search_sources: list[IContextSearchSource],
    ) -> None:
        """Initialize health dependencies.

        Args:
            provider: Optional embedding provider.
            vector_retrieval_enabled: Whether vector retrieval is configured.
            search_sources: Configured retrieval and index sources.
        """
        self._provider = provider
        self._vector_retrieval_enabled = vector_retrieval_enabled
        self._search_sources = search_sources

    def health(self) -> RagDependencyHealth:
        """Return current embedding and vector dependency health.

        Returns:
            Health state for FTS, vector, and embedding dependencies.
        """
        return build_rag_dependency_health(
            embedding_provider=self._provider,
            vector_retrieval_enabled=self._vector_retrieval_enabled,
        )

    async def health_with_index_status(self) -> RagDependencyHealth:
        """Return dependency health including persisted fingerprint status.

        Returns:
            Health state that marks vector recall unavailable on mismatch.
        """
        health = self.health()
        provider = self._provider
        if (
            provider is None
            or not self._vector_retrieval_enabled
            or health.vector is not RagHealthState.HEALTHY
            or health.embedding is not RagHealthState.HEALTHY
        ):
            return health
        try:
            index_status = await _embedding_index_status(
                provider=provider,
                sources=self._search_sources,
            )
            source_statuses = await _embedding_source_statuses(
                provider=provider,
                sources=self._search_sources,
            )
        except SQLAlchemyError as exc:
            return _embedding_index_status_probe_failed_health(health, exc)
        if index_status is not RagHealthState.REINDEX_REQUIRED:
            return replace(health, source_statuses=tuple(source_statuses))
        warnings = [
            *health.warnings,
            (
                "Embedding index status is REINDEX_REQUIRED; vector recall "
                "is disabled across configured sources until all source "
                "fingerprints match; run retrieval reindex before vector recall."
            ),
        ]
        return replace(
            health,
            embedding=RagHealthState.REINDEX_REQUIRED,
            default_strategy=RagStrategy.FTS_ONLY,
            warnings=tuple(warnings),
            source_statuses=tuple(source_statuses),
        )

    async def source_statuses(self) -> list[ContextEmbeddingSourceStatus]:
        """Return source-level embedding fingerprint diagnostics.

        Returns:
            One status object per configured Context retrieval source.
        """
        provider = self._provider
        health = self.health()
        if (
            provider is None
            or not self._vector_retrieval_enabled
            or health.vector is not RagHealthState.HEALTHY
            or health.embedding is not RagHealthState.HEALTHY
        ):
            return []
        return await _embedding_source_statuses(
            provider=provider,
            sources=self._search_sources,
        )


def _embedding_index_status_probe_failed_health(
    health: RagDependencyHealth,
    error: SQLAlchemyError,
) -> RagDependencyHealth:
    warning = (
        "Embedding index status check failed; vector recall is disabled until "
        f"the storage probe succeeds: {error.__class__.__name__}"
    )
    return replace(
        health,
        embedding=RagHealthState.DEGRADED,
        default_strategy=RagStrategy.FTS_ONLY,
        warnings=(*health.warnings, warning),
    )


async def _embedding_source_statuses(
    provider: EmbeddingProvider,
    sources: list[IContextSearchSource],
) -> list[ContextEmbeddingSourceStatus]:
    fingerprint = provider.fingerprint()
    return [
        await source.embedding_source_status(
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            fingerprint_key=fingerprint.key(),
            current_fingerprint=fingerprint.identity_payload(),
        )
        for source in sources
    ]


async def _embedding_index_status(
    provider: EmbeddingProvider,
    sources: list[IContextSearchSource],
) -> RagHealthState:
    fingerprint = provider.fingerprint()
    for source in sources:
        source_status = await source.embedding_index_status(
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            fingerprint_key=fingerprint.key(),
        )
        if source_status is RagHealthState.REINDEX_REQUIRED:
            return source_status
    return RagHealthState.HEALTHY
