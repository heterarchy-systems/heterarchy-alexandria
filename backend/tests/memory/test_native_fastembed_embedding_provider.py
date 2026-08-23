"""Tests for the fail-closed native FastEmbed embedding provider."""

from __future__ import annotations

from typing import cast

import pytest
from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
)
from app.memory.infrastructure.providers.native_fastembed_embedding_provider import (
    NativeFastEmbedEmbeddingProvider,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue


class _FakeNativeFastEmbedModule:
    def __init__(self) -> None:
        self.document_requests: list[JSONObject] = []
        self.query_calls: list[tuple[str, str | None, int]] = []
        self.record_count_offset = 0
        self.query_dimensions = DEFAULT_EMBEDDING_DIMENSIONS

    def compute_contract_version(self) -> int:
        return 1

    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes:
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

    def embed_multilingual_e5_query(
        self,
        query_input: str,
        cache_directory: str | None,
        threads: int,
    ) -> list[float]:
        self.query_calls.append((query_input, cache_directory, threads))
        return [0.25] * self.query_dimensions


def test_native_provider_delegates_documents_and_query_without_python_fallback() -> (
    None
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
    assert runtime == {"cache_directory": "model-cache", "threads": 3}
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
    assert native_module.query_calls == [("query: 관계의 의미", "model-cache", 3)]


def test_native_provider_empty_document_batch_does_not_initialize_runtime() -> None:
    native_module = _FakeNativeFastEmbedModule()
    provider = NativeFastEmbedEmbeddingProvider(native_module=native_module)

    assert provider.embed_documents([]) == []
    assert native_module.document_requests == []


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
