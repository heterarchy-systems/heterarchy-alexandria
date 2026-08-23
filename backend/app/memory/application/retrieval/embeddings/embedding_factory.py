"""Embedding provider composition helpers."""

from __future__ import annotations

from typing import Literal

from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_THREADS,
    EmbeddingProvider,
)
from app.memory.application.retrieval.embeddings.fake_embedding_provider import (
    FakeEmbeddingProvider,
)
from app.memory.infrastructure.providers.native_fastembed_embedding_provider import (
    create_native_fastembed_embedding_provider,
)

EmbeddingProviderName = Literal["fastembed", "fake-test", "disabled"]


def create_embedding_provider(
    vector_enabled: bool,
    provider_name: EmbeddingProviderName,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    cache_dir: str | None = None,
    threads: int = DEFAULT_EMBEDDING_THREADS,
) -> EmbeddingProvider | None:
    """Create the configured local embedding provider.

    Args:
        vector_enabled: Whether vector retrieval is enabled for the service.
        provider_name: Configured embedding provider identifier.
        model_name: Embedding model identifier.
        dimensions: Embedding vector dimension count.
        cache_dir: Optional model cache directory.
        threads: ONNX Runtime thread count for local E5 inference.

    Returns:
        EmbeddingProvider | None: Provider instance when vector recall can embed text.
    """
    if not vector_enabled or provider_name == "disabled":
        return None
    if provider_name == "fake-test":
        return FakeEmbeddingProvider(model_name=model_name, dimensions=dimensions)
    return create_native_fastembed_embedding_provider(
        model_name=model_name,
        dimensions=dimensions,
        cache_dir=cache_dir,
        threads=threads,
    )
