"""RAG dependency health helpers."""

from __future__ import annotations

from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy


def build_rag_dependency_health(
    embedding_provider: EmbeddingProvider | None,
    vector_retrieval_enabled: bool,
) -> RagDependencyHealth:
    """Return current RAG dependency health.

    Args:
        embedding_provider: Optional local embedding provider.
        vector_retrieval_enabled: Whether vector indexing/query paths are wired.
    Returns:
        Health state for FTS, vector, and embedding dependencies.
    """
    embedding_state = (
        RagHealthState.HEALTHY
        if embedding_provider is not None
        else RagHealthState.DEGRADED
    )
    if not vector_retrieval_enabled:
        vector_state = RagHealthState.DISABLED
    else:
        vector_state = RagHealthState.HEALTHY
    default_strategy = (
        RagStrategy.HYBRID
        if vector_state is RagHealthState.HEALTHY
        and embedding_state is RagHealthState.HEALTHY
        else RagStrategy.FTS_ONLY
    )
    warnings = []
    if not vector_retrieval_enabled:
        warnings.append("Vector retrieval is disabled by configuration.")
    if embedding_provider is None:
        warnings.append("Embedding provider not assigned; vector recall disabled.")
    health = RagDependencyHealth(
        fts=RagHealthState.HEALTHY,
        vector=vector_state,
        embedding=embedding_state,
        default_strategy=default_strategy,
        model_name=(
            embedding_provider.model_name
            if embedding_provider is not None
            else DEFAULT_EMBEDDING_MODEL
        ),
        dimensions=(
            embedding_provider.dimensions
            if embedding_provider is not None
            else DEFAULT_EMBEDDING_DIMENSIONS
        ),
        fingerprint=(
            embedding_provider.fingerprint().identity_payload()
            if embedding_provider is not None
            else None
        ),
        warnings=tuple(warnings),
    )
    return health
