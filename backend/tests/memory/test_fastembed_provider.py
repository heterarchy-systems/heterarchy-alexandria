"""FastEmbed provider compatibility tests."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import ClassVar

import pytest
from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
)
from app.memory.application.retrieval.embeddings.fastembed_provider import (
    FastEmbedEmbeddingProvider,
)


@dataclass(frozen=True, slots=True)
class _ModelSource:
    hf: str


class _PoolingType:
    MEAN = "mean"


class _TextEmbeddingStandin:
    """FastEmbed stand-in that captures custom registration and embed inputs."""

    registered: ClassVar[bool] = False
    registration_calls: ClassVar[list[dict[str, object]]] = []
    instances: ClassVar[list[_TextEmbeddingStandin]] = []

    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.threads = threads
        self.query_inputs: list[str] = []
        self.passage_inputs: list[str] = []
        self.embed_inputs: list[str] = []
        self.query_batch_sizes: list[int | None] = []
        self.passage_batch_sizes: list[int | None] = []
        self.embed_batch_sizes: list[int | None] = []
        self.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.registered = False
        cls.registration_calls = []
        cls.instances = []

    @classmethod
    def add_custom_model(cls, **kwargs: object) -> None:
        if cls.registered:
            model = kwargs["model"]
            raise ValueError(f"Model {model} is already registered in TextEmbedding")
        cls.registered = True
        cls.registration_calls.append(kwargs)

    def embed(
        self,
        texts: Iterable[str],
        *,
        batch_size: int | None = None,
    ) -> Iterable[list[float]]:
        prepared = list(texts)
        self.embed_inputs.extend(prepared)
        self.embed_batch_sizes.append(batch_size)
        return ([float(len(text))] for text in prepared)

    def query_embed(
        self,
        query: str | Iterable[str],
        *,
        batch_size: int | None = None,
    ) -> Iterable[list[float]]:
        prepared = [query] if isinstance(query, str) else list(query)
        self.query_inputs.extend(prepared)
        self.query_batch_sizes.append(batch_size)
        return ([float(len(text))] for text in prepared)

    def passage_embed(
        self,
        texts: Iterable[str],
        *,
        batch_size: int | None = None,
    ) -> Iterable[list[float]]:
        prepared = list(texts)
        self.passage_inputs.extend(prepared)
        self.passage_batch_sizes.append(batch_size)
        return ([float(len(text))] for text in prepared)


def _install_fastembed_standin(monkeypatch: pytest.MonkeyPatch) -> None:
    _TextEmbeddingStandin.reset()
    fastembed_module = ModuleType("fastembed")
    fastembed_module.TextEmbedding = _TextEmbeddingStandin
    common_module = ModuleType("fastembed.common")
    description_module = ModuleType("fastembed.common.model_description")
    description_module.ModelSource = _ModelSource
    description_module.PoolingType = _PoolingType
    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)
    monkeypatch.setitem(sys.modules, "fastembed.common", common_module)
    monkeypatch.setitem(
        sys.modules,
        "fastembed.common.model_description",
        description_module,
    )


def test_default_model_registers_e5_and_uses_retrieval_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default model must use E5 query and passage input contracts."""
    _install_fastembed_standin(monkeypatch)
    provider = FastEmbedEmbeddingProvider(cache_dir="/tmp/fastembed-test-cache")

    query_vector = provider.embed_query("alexandria")
    document_vectors = provider.embed_documents(["memory", "검색"])

    instance = _TextEmbeddingStandin.instances[0]
    registration = _TextEmbeddingStandin.registration_calls[0]
    assert DEFAULT_EMBEDDING_MODEL == "intfloat/multilingual-e5-small"
    assert query_vector == [17.0]
    assert document_vectors == [[15.0], [11.0]]
    assert instance.query_inputs == ["query: alexandria"]
    assert instance.passage_inputs == ["passage: memory", "passage: 검색"]
    assert instance.embed_inputs == []
    assert instance.query_batch_sizes == [None]
    assert instance.passage_batch_sizes == [16]
    assert instance.embed_batch_sizes == []
    assert instance.cache_dir == "/tmp/fastembed-test-cache"
    assert instance.threads == 4
    assert registration["model"] == DEFAULT_EMBEDDING_MODEL
    assert registration["pooling"] == _PoolingType.MEAN
    assert registration["normalization"] is True
    assert registration["dim"] == DEFAULT_EMBEDDING_DIMENSIONS
    assert registration["model_file"] == "onnx/model.onnx"
    assert provider.pooling_mode == "mean"
    assert provider.document_input_format.endswith("+e5-passage-prefix-v1")
    assert provider.fingerprint().model == DEFAULT_EMBEDDING_MODEL

    configured_provider = FastEmbedEmbeddingProvider(threads=6)
    configured_provider.embed_query("configured")
    assert _TextEmbeddingStandin.instances[1].threads == 6


def test_e5_custom_model_registration_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple provider instances may reuse the same process-level registration."""
    _install_fastembed_standin(monkeypatch)

    FastEmbedEmbeddingProvider().embed_query("first")
    FastEmbedEmbeddingProvider().embed_query("second")

    assert len(_TextEmbeddingStandin.registration_calls) == 1
    assert len(_TextEmbeddingStandin.instances) == 2


def test_non_e5_model_preserves_unprefixed_fastembed_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit non-E5 models should retain the generic FastEmbed input path."""
    _install_fastembed_standin(monkeypatch)
    provider = FastEmbedEmbeddingProvider(
        model_name="custom/non-e5-model",
        dimensions=8,
    )

    query_vector = provider.embed_query("alexandria")
    document_vectors = provider.embed_documents(["memory"])

    instance = _TextEmbeddingStandin.instances[0]
    assert query_vector == [10.0]
    assert document_vectors == [[6.0]]
    assert instance.embed_inputs == ["alexandria", "memory"]
    assert instance.embed_batch_sizes == [None, 16]
    assert instance.query_inputs == []
    assert instance.passage_inputs == []
    assert instance.threads is None
    assert _TextEmbeddingStandin.registration_calls == []
    assert provider.pooling_mode == "fastembed-default"


def test_fastembed_provider_repairs_incomplete_e5_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A partial E5 cache should redownload only the missing ONNX artifact."""
    _install_fastembed_standin(monkeypatch)
    cache_dir = tmp_path / "fastembed-cache"
    model_root = cache_dir / "models--intfloat--multilingual-e5-small"
    blobs = model_root / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "model.incomplete").write_bytes(b"")
    calls: list[tuple[str, str, tuple[str, ...], bool]] = []

    def snapshot_download(
        *,
        repo_id: str,
        cache_dir: str,
        allow_patterns: list[str],
        force_download: bool,
    ) -> str:
        calls.append((repo_id, cache_dir, tuple(allow_patterns), force_download))
        snapshot = model_root / "snapshots" / "test"
        model_file = snapshot / "onnx" / "model.onnx"
        model_file.parent.mkdir(parents=True)
        model_file.write_bytes(b"onnx")
        return str(snapshot)

    huggingface_module = ModuleType("huggingface_hub")
    huggingface_module.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_module)

    provider = FastEmbedEmbeddingProvider(cache_dir=str(cache_dir))

    assert provider.embed_query("repair") == [13.0]
    assert calls == [
        (
            DEFAULT_EMBEDDING_MODEL,
            str(cache_dir),
            ("onnx/model.onnx",),
            True,
        )
    ]
