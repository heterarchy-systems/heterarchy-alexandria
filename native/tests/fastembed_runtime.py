"""Bootstrap a Rust FastEmbed session from the Python-owned model cache."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Protocol

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FASTEMBED_CACHE = REPOSITORY_ROOT / "native/target/fastembed-parity-cache"


class FastEmbedCacheUnavailableError(FileNotFoundError):
    """Report a missing or incomplete snapshot to offline-only test tools."""


class FastEmbedRuntimeSession(Protocol):
    """Opaque per-provider native session shared by numerical and perf tools."""

    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...

    def embed_query(self, query_input: str) -> list[float]: ...


class FastEmbedRuntimeBuilder(Protocol):
    """Ephemeral native receiver for bounded chunks of the five model assets."""

    def begin_asset(self, name: str, size: int) -> None: ...

    def write_chunk(self, chunk: bytes) -> None: ...

    def asset_verified(self, name: str) -> None: ...

    def finish(self) -> FastEmbedRuntimeSession: ...

    def close(self) -> None: ...


class FastEmbedRuntimeModule(Protocol):
    """Native module surface used only to create an opaque session."""

    def embedding_runtime_contract_version(self) -> int: ...

    def create_multilingual_e5_runtime_builder(
        self,
        threads: int,
    ) -> FastEmbedRuntimeBuilder: ...


@dataclass(frozen=True, slots=True)
class FastEmbedRuntimeBootstrap:
    """Measured Python stream transfer and native builder completion."""

    session: FastEmbedRuntimeSession
    revision: str
    bootstrap_nanoseconds: int
    artifact_stream_transfer_nanoseconds: int
    native_finish_nanoseconds: int


def bootstrap_cached_fastembed_runtime(
    native_module: FastEmbedRuntimeModule,
    cache_directory: Path,
    *,
    threads: int,
) -> FastEmbedRuntimeBootstrap:
    """Stream cached model assets through the Python owner into a Rust session."""
    bootstrap_started = perf_counter_ns()
    if native_module.embedding_runtime_contract_version() != 4:
        raise AssertionError("native embedding runtime contract version must be 4")

    from app.memory.infrastructure.providers.embedding_model_artifacts import (
        stream_cached_embedding_model_artifacts,
    )
    from app.platform.config.memory_config import (
        EmbeddingModelArtifactConfig,
    )

    resolved_cache = cache_directory.resolve()
    config = EmbeddingModelArtifactConfig(
        _env_file=None,
        hf_home=None,
        fallback_cache_dir=resolved_cache,
        endpoint="https://huggingface.co",
        ort_load_config_from_model=None,
        token_path=resolved_cache / "unused-offline-token",
    )
    builder = native_module.create_multilingual_e5_runtime_builder(threads)
    started = perf_counter_ns()
    try:
        revision = stream_cached_embedding_model_artifacts(
            cache_dir=str(resolved_cache),
            config=config,
            sink=builder,
        )
        if revision is None:
            raise FastEmbedCacheUnavailableError(
                "complete model snapshot required for offline probe"
            )
        artifact_stream_transfer_nanoseconds = perf_counter_ns() - started

        started = perf_counter_ns()
        session = builder.finish()
        native_finish_nanoseconds = perf_counter_ns() - started
    finally:
        builder.close()

    return FastEmbedRuntimeBootstrap(
        session=session,
        revision=revision,
        bootstrap_nanoseconds=perf_counter_ns() - bootstrap_started,
        artifact_stream_transfer_nanoseconds=artifact_stream_transfer_nanoseconds,
        native_finish_nanoseconds=native_finish_nanoseconds,
    )
