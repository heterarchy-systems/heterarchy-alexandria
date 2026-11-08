"""Tests for the fail-closed native FastEmbed embedding provider."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import cast

import pytest

from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
)
from app.memory.infrastructure.providers import native_fastembed_embedding_provider
from app.memory.infrastructure.providers.native_fastembed_embedding_provider import (
    NativeFastEmbedEmbeddingProvider,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_ASSETS = (
    ("onnx/model.onnx", b"model"),
    ("tokenizer.json", b"tokenizer"),
    ("config.json", b"config"),
    ("special_tokens_map.json", b"special"),
    ("tokenizer_config.json", b"tokenizer-config"),
)


class _FakeBuilder:
    def __init__(self, module: _FakeNativeFastEmbedModule, threads: int) -> None:
        self.module = module
        self.threads = threads
        self.buffers: dict[str, bytearray] = {}
        self.asset_sizes: dict[str, int] = {}
        self.current = ""
        self.verified_assets: list[str] = []
        self.close_calls = 0
        self.finish_calls = 0
        self.pending_onnx_prepared = False
        self.prepared_state_dropped = False

    def begin_asset(self, name: str, size: int) -> None:
        self.current = name
        self.asset_sizes[name] = size
        self.buffers[name] = bytearray()

    def write_chunk(self, chunk: bytes) -> None:
        self.buffers[self.current].extend(chunk)

    def asset_verified(self, name: str) -> None:
        if self.current != name or len(self.buffers[name]) != self.asset_sizes[name]:
            raise AssertionError("asset verification requires complete matching bytes")
        self.verified_assets.append(name)
        if name == "onnx/model.onnx":
            self.pending_onnx_prepared = True

    def finish(self) -> _FakeFastEmbedSession:
        self.finish_calls += 1
        if self.verified_assets != [name for name, _ in _ASSETS]:
            raise AssertionError("session finish requires every asset to be verified")
        content = [bytes(self.buffers[name]) for name, _ in _ASSETS]
        self.buffers.clear()
        self.pending_onnx_prepared = False
        return self.module.complete_bootstrap(*content, self.threads)

    def close(self) -> None:
        if self.pending_onnx_prepared:
            self.prepared_state_dropped = True
        self.pending_onnx_prepared = False
        self.buffers.clear()
        self.close_calls += 1


class _FakeNativeFastEmbedModule:
    def __init__(self) -> None:
        self.document_requests: list[JSONObject] = []
        self.document_session_ids: list[int] = []
        self.query_calls: list[tuple[int, str]] = []
        self.bootstrap_calls: list[tuple[bytes, bytes, bytes, bytes, bytes, int]] = []
        self.bootstrap_failures = 0
        self.builders: list[_FakeBuilder] = []
        self.sessions: list[_FakeFastEmbedSession] = []
        self.runtime_version = 4
        self.record_count_offset = 0
        self.query_dimensions = DEFAULT_EMBEDDING_DIMENSIONS

    def compute_contract_version(self) -> int:
        return 1

    def embedding_runtime_contract_version(self) -> int:
        return self.runtime_version

    def create_multilingual_e5_runtime_builder(self, threads: int) -> _FakeBuilder:
        builder = _FakeBuilder(self, threads)
        self.builders.append(builder)
        return builder

    def complete_bootstrap(
        self,
        onnx: bytes,
        tokenizer: bytes,
        config: bytes,
        special_tokens_map: bytes,
        tokenizer_config: bytes,
        threads: int,
    ) -> _FakeFastEmbedSession:
        self.bootstrap_calls.append(
            (onnx, tokenizer, config, special_tokens_map, tokenizer_config, threads)
        )
        if self.bootstrap_failures:
            self.bootstrap_failures -= 1
            raise ValueError("native initialization failed")
        session = _FakeFastEmbedSession(self, len(self.sessions))
        self.sessions.append(session)
        return session

    def _run_bulk_embedding_batch_json(
        self,
        session_id: int,
        payload: bytes,
    ) -> bytes:
        decoded = loads_json(payload)
        if not isinstance(decoded, dict):
            raise AssertionError("test request must be an object")
        self.document_requests.append(decoded)
        request = decoded.get("request")
        if not isinstance(request, dict):
            raise AssertionError("test request envelope must contain request")
        documents = request.get("documents")
        if not isinstance(documents, list):
            raise AssertionError("test request must contain documents")
        self.document_session_ids.append(session_id)
        output_count = max(0, len(documents) + self.record_count_offset)
        records: list[JSONValue] = [
            {
                "input_index": index,
                "item_id": f"embedding-{index}",
                "dimensions": DEFAULT_EMBEDDING_DIMENSIONS,
                "vector": _vector(float(index + 1)),
            }
            for index in range(output_count)
        ]
        response: JSONObject = {
            "contract_version": 1,
            "embedding_version": 1,
            "model": request.get("model"),
            "records": records,
            "metrics": {
                "item_count": output_count,
                "batch_count": 1,
                "dimensions": DEFAULT_EMBEDDING_DIMENSIONS,
                "vector_value_count": output_count * DEFAULT_EMBEDDING_DIMENSIONS,
            },
        }
        return dumps_json(cast(JSONValue, response))


class _FakeFastEmbedSession:
    def __init__(self, module: _FakeNativeFastEmbedModule, session_id: int) -> None:
        self.module = module
        self.session_id = session_id

    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes:
        return self.module._run_bulk_embedding_batch_json(self.session_id, payload)

    def embed_query(
        self,
        query_input: str,
    ) -> list[float]:
        self.module.query_calls.append((self.session_id, query_input))
        return [0.25] * self.module.query_dimensions


@pytest.fixture(autouse=True)
def artifact_reads(monkeypatch):
    calls = []

    def stream(cache_dir, config, sink):
        calls.append((cache_dir, config))
        for name, content in _ASSETS:
            sink.begin_asset(name, len(content))
            sink.write_chunk(content)
            sink.asset_verified(name)
        return "1" * 40

    monkeypatch.setattr(
        native_fastembed_embedding_provider,
        "stream_embedding_model_artifacts",
        stream,
        raising=False,
    )
    return calls


def test_native_provider_delegates_documents_and_query_without_python_fallback(
    artifact_reads,
):
    native_module = _FakeNativeFastEmbedModule()
    provider = NativeFastEmbedEmbeddingProvider(
        native_module=native_module,
        cache_dir="model-cache",
        threads=3,
    )

    vectors = provider.embed_documents([" first document ", "두 번째 문서"])
    query_vector = provider.embed_query("  관계의 의미  ")

    assert len(vectors) == 2
    assert all(len(vector) == DEFAULT_EMBEDDING_DIMENSIONS for vector in vectors)
    assert len(query_vector) == DEFAULT_EMBEDDING_DIMENSIONS
    assert provider.provider_name == "FASTEMBED_LOCAL"
    assert provider.provider_version == "5.17.4"
    assert provider.pooling_mode == "mean"
    assert provider.normalize is True
    assert provider.document_input_format.endswith("+e5-passage-prefix-v1")

    request = native_module.document_requests[0]
    runtime = request.get("runtime")
    request_body = request.get("request")
    assert isinstance(runtime, dict)
    assert isinstance(request_body, dict)
    assert runtime == {"version": 4}
    assert request_body.get("batch_size") == 16
    model = request_body.get("model")
    documents = request_body.get("documents")
    assert isinstance(model, dict)
    assert isinstance(documents, list)
    assert model.get("model") == "intfloat/multilingual-e5-small"
    assert model.get("input_kind") == "e5_passage"
    assert documents == [
        {
            "item_id": "embedding-0",
            "content": " first document ",
            "title": None,
            "heading": None,
        },
        {
            "item_id": "embedding-1",
            "content": "두 번째 문서",
            "title": None,
            "heading": None,
        },
    ]
    assert native_module.query_calls == [(0, "query: 관계의 의미")]
    assert native_module.document_session_ids == [0]
    assert len(artifact_reads) == 1
    assert artifact_reads[0][0] == "model-cache"
    assert native_module.bootstrap_calls == [
        (b"model", b"tokenizer", b"config", b"special", b"tokenizer-config", 3)
    ]
    assert native_module.builders[0].close_calls == 1
    assert native_module.builders[0].buffers == {}
    assert native_module.builders[0].verified_assets == [name for name, _ in _ASSETS]


def test_native_provider_empty_document_batch_does_not_initialize_runtime(
    artifact_reads,
) -> None:
    native_module = _FakeNativeFastEmbedModule()
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)

    assert provider.embed_documents([]) == []
    assert native_module.document_requests == []
    assert native_module.bootstrap_calls == []
    assert artifact_reads == []


def test_native_provider_rejects_unsupported_configuration() -> None:
    native_module = _FakeNativeFastEmbedModule()

    with pytest.raises(ValueError, match="only multilingual-e5-small"):
        NativeFastEmbedEmbeddingProvider(
            native_module=native_module,
            model_name="unsupported-model",
        )
    with pytest.raises(ValueError, match="requires 384 dimensions"):
        NativeFastEmbedEmbeddingProvider(
            native_module=native_module,
            dimensions=DEFAULT_EMBEDDING_DIMENSIONS - 1,
        )
    with pytest.raises(ValueError, match="threads must be positive"):
        NativeFastEmbedEmbeddingProvider(native_module=native_module, threads=0)


def test_native_provider_rejects_document_cardinality_drift() -> None:
    native_module = _FakeNativeFastEmbedModule()
    native_module.record_count_offset = -1
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)

    with pytest.raises(ValueError, match="unexpected record cardinality"):
        provider.embed_documents(["one", "two"])


def test_native_provider_rejects_query_dimension_drift() -> None:
    native_module = _FakeNativeFastEmbedModule()
    native_module.query_dimensions = DEFAULT_EMBEDDING_DIMENSIONS - 1
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)

    with pytest.raises(ValueError, match="query vector has unexpected dimensions"):
        provider.embed_query("query")


def _vector(seed: float) -> list[float]:
    return [seed / DEFAULT_EMBEDDING_DIMENSIONS] * DEFAULT_EMBEDDING_DIMENSIONS


def test_bootstrap_failure_is_not_published_and_next_call_retries(
    artifact_reads,
) -> None:
    native_module = _FakeNativeFastEmbedModule()
    native_module.bootstrap_failures = 1
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)
    with pytest.raises(ValueError, match="native initialization failed"):
        provider.embed_query("first")
    assert native_module.query_calls == []
    provider.embed_query("second")
    provider.embed_query("third")
    assert len(native_module.bootstrap_calls) == 2
    assert len(artifact_reads) == 2
    assert len(native_module.query_calls) == 2
    assert len(native_module.sessions) == 1
    assert all(builder.close_calls == 1 for builder in native_module.builders)


def test_provider_sessions_are_independent_per_provider(artifact_reads) -> None:
    native_module = _FakeNativeFastEmbedModule()
    first = NativeFastEmbedEmbeddingProvider(native_module=native_module)
    second = NativeFastEmbedEmbeddingProvider(native_module=native_module)

    first.embed_query("first provider")
    second.embed_query("second provider")

    assert len(native_module.sessions) == 2
    assert native_module.sessions[0] is not native_module.sessions[1]
    assert native_module.query_calls == [
        (0, "query: first provider"),
        (1, "query: second provider"),
    ]
    assert len(artifact_reads) == 2
    assert all(builder.close_calls == 1 for builder in native_module.builders)


def test_runtime_version_mismatch_fails_before_artifact_read(artifact_reads) -> None:
    native_module = _FakeNativeFastEmbedModule()
    native_module.runtime_version = 1
    with pytest.raises(ValueError, match="runtime contract version"):
        NativeFastEmbedEmbeddingProvider(native_module=native_module)
    assert artifact_reads == []


def test_concurrent_first_uses_share_one_completed_bootstrap(artifact_reads) -> None:
    started = Event()
    release = Event()
    callers = Barrier(3)

    class BlockingModule(_FakeNativeFastEmbedModule):
        def complete_bootstrap(self, *args) -> _FakeFastEmbedSession:
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("bootstrap fixture was not released")
            return super().complete_bootstrap(*args)

    native_module = BlockingModule()
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)

    def query(index: int) -> list[float]:
        callers.wait(timeout=5)
        return provider.embed_query(str(index))

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(query, index) for index in range(3)]
        try:
            assert started.wait(timeout=3)
            assert all(not future.done() for future in futures)
        finally:
            release.set()
        assert all(len(future.result(timeout=5)) == 384 for future in futures)
    assert len(artifact_reads) == 1
    assert len(native_module.bootstrap_calls) == 1
    assert len(native_module.query_calls) == 3
    assert {session_id for session_id, _ in native_module.query_calls} == {0}
    assert len(native_module.sessions) == 1


def test_artifact_acquisition_failure_closes_builder_and_retries(
    monkeypatch,
    artifact_reads,
) -> None:
    stream = native_fastembed_embedding_provider.stream_embedding_model_artifacts
    attempts = 0

    def fail_once(cache_dir, config, sink):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            sink.begin_asset("onnx/model.onnx", 7)
            sink.write_chunk(b"partial")
            raise ValueError("artifact acquisition failed")
        return stream(cache_dir, config, sink)

    native_module = _FakeNativeFastEmbedModule()
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)
    monkeypatch.setattr(
        native_fastembed_embedding_provider,
        "stream_embedding_model_artifacts",
        fail_once,
    )

    with pytest.raises(ValueError, match="artifact acquisition failed"):
        provider.embed_query("first")

    assert native_module.bootstrap_calls == []
    assert native_module.sessions == []
    assert native_module.builders[0].buffers == {}
    assert native_module.builders[0].close_calls == 1

    provider.embed_query("retry")

    assert len(artifact_reads) == 1
    assert len(native_module.sessions) == 1
    assert len(native_module.query_calls) == 1
    assert all(builder.close_calls == 1 for builder in native_module.builders)


def test_stream_validation_failure_closes_buffers_without_publishing(
    monkeypatch, artifact_reads
) -> None:
    stream = native_fastembed_embedding_provider.stream_embedding_model_artifacts

    def broken_stream(cache_dir, config, sink):
        sink.begin_asset("onnx/model.onnx", 7)
        sink.write_chunk(b"partial")
        raise ValueError("snapshot changed")

    native_module = _FakeNativeFastEmbedModule()
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)
    monkeypatch.setattr(
        native_fastembed_embedding_provider,
        "stream_embedding_model_artifacts",
        broken_stream,
    )
    with pytest.raises(ValueError, match="snapshot changed"):
        provider.embed_query("first")
    assert native_module.bootstrap_calls == []
    assert native_module.sessions == []
    assert native_module.builders[0].buffers == {}
    assert native_module.builders[0].close_calls == 1
    monkeypatch.setattr(
        native_fastembed_embedding_provider,
        "stream_embedding_model_artifacts",
        stream,
    )
    provider.embed_query("retry")
    assert len(native_module.builders) == 2
    assert len(native_module.bootstrap_calls) == 1
    assert len(native_module.sessions) == 1


def test_later_reference_failure_drops_verified_onnx_preparation(
    monkeypatch,
    artifact_reads,
) -> None:
    def reference_drift_after_onnx(cache_dir, config, sink):
        onnx_name, onnx_bytes = _ASSETS[0]
        sink.begin_asset(onnx_name, len(onnx_bytes))
        sink.write_chunk(onnx_bytes)
        sink.asset_verified(onnx_name)
        tokenizer_name, tokenizer_bytes = _ASSETS[1]
        sink.begin_asset(tokenizer_name, len(tokenizer_bytes))
        sink.write_chunk(tokenizer_bytes[:2])
        raise ValueError("cached reference changed during read")

    native_module = _FakeNativeFastEmbedModule()
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)
    monkeypatch.setattr(
        native_fastembed_embedding_provider,
        "stream_embedding_model_artifacts",
        reference_drift_after_onnx,
    )

    with pytest.raises(ValueError, match="cached reference changed during read"):
        provider.embed_query("first")

    builder = native_module.builders[0]
    assert builder.verified_assets == ["onnx/model.onnx"]
    assert builder.finish_calls == 0
    assert builder.pending_onnx_prepared is False
    assert builder.prepared_state_dropped is True
    assert builder.buffers == {}
    assert builder.close_calls == 1
    assert native_module.bootstrap_calls == []
    assert native_module.sessions == []
    assert native_module.query_calls == []


@pytest.mark.parametrize(
    "enabled,provider_name", [(False, "fastembed"), (True, "fake-test")]
)
def test_inactive_native_embedding_does_not_resolve_artifact_settings(
    monkeypatch, enabled: bool, provider_name: str
) -> None:
    from tests.config_test_data import (
        embedding_config_values,
        vault_config_values,
    )

    from app.memory.containers import MemoryContainer
    from app.platform.config.memory_config import EmbeddingConfig
    from app.platform.config.vault_config import VaultConfig

    monkeypatch.setenv("ORT_LOAD_CONFIG_FROM_MODEL", "1")
    container = MemoryContainer(
        embedding_config=EmbeddingConfig(
            _env_file=None,
            **embedding_config_values(
                rag_vector_enabled=enabled,
                rag_embedding_provider=provider_name,
            ),
        ),
        vault_config=VaultConfig(_env_file=None, **vault_config_values()),
    )
    provider = container.embedding_provider()
    if enabled:
        assert provider is not None
        assert provider.provider_name == "FAKE_LOCAL"
    else:
        assert provider is None
