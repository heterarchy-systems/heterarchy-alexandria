"""FastEmbed local embedding provider."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Final

from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_THREADS,
    EmbeddingProvider,
)
from app.memory.application.retrieval.embeddings.embedding_document import (
    EMBEDDING_DOCUMENT_INPUT_FORMAT,
)

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_MULTILINGUAL_E5_SMALL_MODEL: Final[str] = "intfloat/multilingual-e5-small"
_E5_QUERY_PREFIX: Final[str] = "query: "
_E5_PASSAGE_PREFIX: Final[str] = "passage: "
_E5_DOCUMENT_INPUT_FORMAT: Final[str] = (
    f"{EMBEDDING_DOCUMENT_INPUT_FORMAT}+e5-passage-prefix-v1"
)
_E5_MODEL_FILE: Final[str] = "onnx/model.onnx"
_FASTEMBED_BATCH_SIZE: Final[int] = 16


class FastEmbedEmbeddingProvider(EmbeddingProvider):
    """Lazy FastEmbed wrapper that does not download models until used.

    Provider metadata is exposed through read-only properties; the only behavioral
    operations are document and query embedding over one lazily initialized model.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        cache_dir: str | None = None,
        threads: int = DEFAULT_EMBEDDING_THREADS,
    ) -> None:
        """Initialize provider configuration.

        Args:
            model_name: FastEmbed-supported model name.
            dimensions: Expected embedding dimensions.
            cache_dir: Optional local model cache directory.
            threads: ONNX Runtime thread count for the E5 model.
        """
        self._model_name = model_name
        self._dimensions = dimensions
        self._cache_dir = cache_dir
        self._threads = threads
        self._model: TextEmbedding | None = None
        self._model_initialization_lock = Lock()

    @property
    def provider_name(self) -> str:
        """Return provider identifier.

        Returns:
            Stable provider name.
        """
        provider_name = "FASTEMBED_LOCAL"
        return provider_name

    @property
    def model_name(self) -> str:
        """Return FastEmbed model name.

        Returns:
            Local FastEmbed model identifier.
        """
        model_name = self._model_name
        return model_name

    @property
    def dimensions(self) -> int:
        """Return configured vector dimensions.

        Returns:
            Embedding vector size.
        """
        dimensions = self._dimensions
        return dimensions

    @property
    def provider_version(self) -> str:
        """Return installed FastEmbed package version.

        Returns:
            Installed FastEmbed version or unknown when unavailable.
        """
        try:
            provider_version = version("fastembed")
        except PackageNotFoundError:
            provider_version = "unknown"
        return provider_version

    @property
    def pooling_mode(self) -> str:
        """Return the FastEmbed pooling mode tracked by this wrapper.

        Returns:
            Stable pooling identifier for mismatch detection.
        """
        pooling_mode = (
            "mean" if self._uses_multilingual_e5_small else "fastembed-default"
        )
        return pooling_mode

    @property
    def document_input_format(self) -> str:
        """Return the persisted document input composition identifier.

        Returns:
            Stable document input format including the E5 passage prefix contract.
        """
        if self._uses_multilingual_e5_small:
            return _E5_DOCUMENT_INPUT_FORMAT
        return EMBEDDING_DOCUMENT_INPUT_FORMAT

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document chunks with FastEmbed.

        Args:
            texts: Ordered document texts.

        Returns:
            One embedding vector per input text.
        """
        model = self._embedding_model()
        prepared_texts = list(texts)
        if self._uses_multilingual_e5_small:
            prepared_texts = [
                f"{_E5_PASSAGE_PREFIX}{text.strip()}" for text in prepared_texts
            ]
            embedded = model.passage_embed(
                prepared_texts,
                batch_size=_FASTEMBED_BATCH_SIZE,
            )
        else:
            embedded = model.embed(
                prepared_texts,
                batch_size=_FASTEMBED_BATCH_SIZE,
            )
        vectors = [list(vector) for vector in embedded]
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed one query with FastEmbed.

        Args:
            text: Query text.

        Returns:
            Query embedding vector.
        """
        model = self._embedding_model()
        if self._uses_multilingual_e5_small:
            embedded = model.query_embed(f"{_E5_QUERY_PREFIX}{text.strip()}")
        else:
            embedded = model.embed([text])
        return list(next(iter(embedded)))

    @property
    def _uses_multilingual_e5_small(self) -> bool:
        return self._model_name == _MULTILINGUAL_E5_SMALL_MODEL

    def _embedding_model(self) -> TextEmbedding:
        model = self._model
        if model is not None:
            return model
        with self._model_initialization_lock:
            model = self._model
            if model is None:
                # lazy import justified: optional FastEmbed dependency loads only when embeddings are requested.
                from fastembed import TextEmbedding

                if self._uses_multilingual_e5_small:
                    self._register_multilingual_e5_small(TextEmbedding)
                    self._repair_incomplete_multilingual_e5_cache()
                embedding_threads = (
                    self._threads if self._uses_multilingual_e5_small else None
                )
                if self._cache_dir is None:
                    model = TextEmbedding(
                        model_name=self._model_name,
                        threads=embedding_threads,
                    )
                else:
                    model = TextEmbedding(
                        model_name=self._model_name,
                        cache_dir=self._cache_dir,
                        threads=embedding_threads,
                    )
                self._model = model
        return model

    @staticmethod
    def _register_multilingual_e5_small(
        text_embedding_type: type[TextEmbedding],
    ) -> None:
        """Register multilingual-e5-small through FastEmbed's custom model API.

        Args:
            text_embedding_type: FastEmbed TextEmbedding class.

        Returns:
            None.
        """
        # local import justified: custom model descriptors load only for optional model registration.
        from fastembed.common.model_description import ModelSource, PoolingType

        try:
            text_embedding_type.add_custom_model(
                model=_MULTILINGUAL_E5_SMALL_MODEL,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=_MULTILINGUAL_E5_SMALL_MODEL),
                dim=DEFAULT_EMBEDDING_DIMENSIONS,
                model_file=_E5_MODEL_FILE,
                description="Multilingual E5 small retrieval embeddings",
                license="mit",
                size_in_gb=0.47,
            )
        except ValueError as exc:
            if "already registered" not in str(exc):
                raise

    def _repair_incomplete_multilingual_e5_cache(self) -> None:
        """Redownload the E5 ONNX artifact when a partial cache is detected."""
        if self._cache_dir is None:
            return
        cache_root = Path(self._cache_dir)
        if not cache_root.exists():
            return
        model_roots = [
            path
            for path in cache_root.iterdir()
            if path.is_dir() and "multilingual-e5-small" in path.name
        ]
        if not model_roots:
            return
        if any(
            model_file.is_file() and model_file.stat().st_size > 0
            for model_root in model_roots
            for model_file in model_root.rglob(Path(_E5_MODEL_FILE).name)
        ):
            return
        # local import justified: Hugging Face recovery is needed only for a detected partial model cache.
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=_MULTILINGUAL_E5_SMALL_MODEL,
            cache_dir=self._cache_dir,
            allow_patterns=[_E5_MODEL_FILE],
            force_download=True,
        )
