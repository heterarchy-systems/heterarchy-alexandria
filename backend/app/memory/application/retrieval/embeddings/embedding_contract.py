"""Abstract contract for text embedding providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.memory.application.retrieval.embeddings.embedding_document import (
    EMBEDDING_DOCUMENT_INPUT_FORMAT,
)
from app.memory.application.retrieval.embeddings.embedding_fingerprint import (
    EmbeddingFingerprint,
)
from app.shared.types.embedding_types import EMBEDDING_VECTOR_DIMENSIONS

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_EMBEDDING_DIMENSIONS = EMBEDDING_VECTOR_DIMENSIONS
DEFAULT_EMBEDDING_THREADS = 4


class EmbeddingProvider(ABC):
    """Abstract contract for local text embedding providers.

    Most public members are read-only provider metadata properties; only document
    and query embedding are behavioral methods. The unified contract guarantees
    one coherent fingerprint and vector dimension boundary.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return provider identifier.

        Returns:
            Stable provider name.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return model identifier.

        Returns:
            Local embedding model name.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return vector dimensions.

        Returns:
            Embedding vector size.
        """

    @property
    def provider_version(self) -> str:
        """Return embedding implementation version.

        Returns:
            Provider library or test implementation version.
        """
        return "unknown"

    @property
    def pooling_mode(self) -> str:
        """Return document/query pooling mode.

        Returns:
            Stable pooling identifier.
        """
        return "default"

    @property
    def normalize(self) -> bool:
        """Return whether embeddings are normalized before storage.

        Returns:
            True when the provider stores normalized vectors.
        """
        return True

    @property
    def document_input_format(self) -> str:
        """Return the document-text composition version included in fingerprints.

        Returns:
            Stable document input format identifier.
        """
        return EMBEDDING_DOCUMENT_INPUT_FORMAT

    def fingerprint(self) -> EmbeddingFingerprint:
        """Return the current embedding generation fingerprint.

        Returns:
            Stable fingerprint for mismatch detection.
        """
        return EmbeddingFingerprint(
            provider=self.provider_name,
            model=self.model_name,
            provider_version=self.provider_version,
            pooling_mode=self.pooling_mode,
            normalize=self.normalize,
            dimensions=self.dimensions,
            document_input_format=self.document_input_format,
        )

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document chunks.

        Args:
            texts: Ordered document texts.

        Returns:
            One embedding vector per input text.
        """

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed one search query.

        Args:
            text: Query text.

        Returns:
            Query embedding vector.
        """
