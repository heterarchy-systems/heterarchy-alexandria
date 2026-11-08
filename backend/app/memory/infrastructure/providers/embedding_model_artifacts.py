"""Stream the fixed multilingual-E5 snapshot through Python-owned IO."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from app.memory.infrastructure.providers.artifact_cache.artifact_contracts import (
    SinkProtocol as EmbeddingModelArtifactSink,
)
from app.memory.infrastructure.providers.artifact_cache.artifact_session import (
    ArtifactCache,
)
from app.platform.config.memory_config import (
    EmbeddingModelArtifactConfig,
)


class _EmbeddingModelArtifactError(ValueError):
    """Represent a sanitized, expected artifact-acquisition failure."""


def stream_embedding_model_artifacts(
    cache_dir: str | None,
    config: EmbeddingModelArtifactConfig,
    sink: EmbeddingModelArtifactSink,
) -> str:
    """Stream a pinned snapshot, importing HTTP acquisition only after a cache miss.

    Args:
        cache_dir: Legacy explicit cache root supplied by the provider.
        config: Captured legacy environment settings and token-file location.
        sink: Caller-owned builder that receives named assets and bounded chunks.

    Returns:
        The validated pinned model revision.
    """
    try:
        cache_root = _resolve_cache_root(cache_dir, config)
        with ArtifactCache(cache_root) as cache:
            revision = cache.reader.stream_complete_snapshot(sink)
            if revision is not None:
                return revision
            from app.memory.infrastructure.providers.embedding_model_artifact_acquisition import (
                acquire_and_stream,
            )

            return acquire_and_stream(cache, config, sink)
    except _EmbeddingModelArtifactError:
        raise
    except OSError, UnicodeError:
        _artifact_error("cache or remote operation failed")


def stream_cached_embedding_model_artifacts(
    cache_dir: str | None,
    config: EmbeddingModelArtifactConfig,
    sink: EmbeddingModelArtifactSink,
) -> str | None:
    """Stream only a complete cached snapshot without acquisition side effects.

    Args:
        cache_dir: Legacy explicit cache root supplied by the caller.
        config: Captured legacy environment settings.
        sink: Caller-owned receiver for bounded asset chunks.

    Returns:
        The validated pinned revision, or None when the cache is absent/incomplete.
    """
    try:
        cache_root = _resolve_cache_root(cache_dir, config)
        with ArtifactCache(cache_root) as cache:
            return cache.reader.stream_complete_snapshot(sink)
    except _EmbeddingModelArtifactError:
        raise
    except OSError, UnicodeError:
        _artifact_error("cached model stream failed")


def _artifact_error(reason: str) -> NoReturn:
    """Raise one stable sanitized artifact failure."""
    raise _EmbeddingModelArtifactError(
        f"EMBEDDING_MODEL_ARTIFACT_ERROR: {reason}"
    ) from None


def _resolve_cache_root(
    cache_dir: str | None,
    config: EmbeddingModelArtifactConfig,
) -> Path:
    """Resolve the legacy cache root with its established precedence."""
    if config.hf_home is not None:
        selected = config.hf_home
    elif cache_dir is not None:
        if not cache_dir.strip():
            _artifact_error("cache path is invalid")
        selected = Path(cache_dir)
    else:
        selected = config.fallback_cache_dir
    try:
        return selected.resolve(strict=False)
    except OSError, RuntimeError, ValueError:
        _artifact_error("cache path is invalid")
