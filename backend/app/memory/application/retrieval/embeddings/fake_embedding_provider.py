"""Deterministic embedding provider for tests and offline paths."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic local provider for tests and offline fallback paths."""

    def __init__(
        self,
        model_name: str = "fake-local-embedding",
        dimensions: int = 8,
        provider_name: str = "FAKE_LOCAL",
    ) -> None:
        """Initialize deterministic provider settings.

        Args:
            model_name: Local fake model identifier.
            dimensions: Embedding vector size.
            provider_name: Local fake provider identifier.

        Returns:
            None.
        """
        self._model_name = model_name
        self._dimensions = dimensions
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        """Return provider identifier.

        Returns:
            Stable provider name.
        """
        provider_name = self._provider_name
        return provider_name

    @property
    def model_name(self) -> str:
        """Return model identifier.

        Returns:
            Fake model name.
        """
        model_name = self._model_name
        return model_name

    @property
    def dimensions(self) -> int:
        """Return vector dimensions.

        Returns:
            Fake vector size.
        """
        dimensions = self._dimensions
        return dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document chunks deterministically without external downloads.

        Args:
            texts: Ordered document texts.

        Returns:
            One deterministic vector per text.
        """
        vectors = [self._embed(text) for text in texts]
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed one query deterministically.

        Args:
            text: Query text.

        Returns:
            Deterministic query vector.
        """
        vector = self._embed(text)
        return vector

    def _embed(self, text: str) -> list[float]:
        """Execute embed.

        Args:
            text: Text used by this operation.

        Returns:
            list[float] result produced by embed.
        """
        buckets = [0.0 for _ in range(self.dimensions)]
        for index, byte in enumerate(text.encode("utf-8")):
            buckets[index % self.dimensions] += float(byte) / 255.0
        magnitude = sum(value * value for value in buckets) ** 0.5 or 1.0
        return [value / magnitude for value in buckets]
