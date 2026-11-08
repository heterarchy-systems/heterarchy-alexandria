"""Keep the parity and perf probes read-only for incomplete model caches."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest

from app.memory.infrastructure.providers import embedding_model_artifacts

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NATIVE_TESTS_DIRECTORY = REPOSITORY_ROOT / "native" / "tests"


class _RuntimeBuilder:
    def __init__(self) -> None:
        self.begin_asset_calls: list[tuple[str, int]] = []
        self.write_chunk_calls = 0
        self.asset_verified_calls: list[str] = []
        self.finish_calls = 0
        self.close_calls = 0

    def begin_asset(self, name: str, size: int) -> None:
        self.begin_asset_calls.append((name, size))

    def write_chunk(self, chunk: bytes) -> None:
        self.write_chunk_calls += 1

    def asset_verified(self, name: str) -> None:
        self.asset_verified_calls.append(name)

    def finish(self) -> _RuntimeSession:
        self.finish_calls += 1
        return _RuntimeSession()

    def close(self) -> None:
        self.close_calls += 1


class _RuntimeSession:
    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes:
        return b"{}"

    def embed_query(self, query_input: str) -> list[float]:
        return []


class _NativeModule:
    def __init__(self, builder: _RuntimeBuilder) -> None:
        self.builder = builder

    def embedding_runtime_contract_version(self) -> int:
        return 4

    def create_multilingual_e5_runtime_builder(
        self,
        threads: int,
    ) -> _RuntimeBuilder:
        assert threads == 4
        return self.builder


def _native_test_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, ModuleType]:
    monkeypatch.syspath_prepend(str(NATIVE_TESTS_DIRECTORY))
    return (
        importlib.import_module("fastembed_runtime"),
        importlib.import_module("bulk_embedding_perf"),
    )


def _partial_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "partial-model-cache"
    cache.mkdir()
    (cache / "incomplete-asset").write_bytes(b"partial")
    return cache


def _configure_read_only_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str | None, object, object]]:
    calls: list[tuple[str | None, object, object]] = []

    def cache_miss(
        cache_dir: str | None,
        config: object,
        sink: object,
    ) -> None:
        calls.append((cache_dir, config, sink))
        return None

    def acquisition_is_forbidden(
        cache_dir: str | None,
        config: object,
        sink: object,
    ) -> str:
        raise AssertionError("offline test tools must not acquire model artifacts")

    monkeypatch.setattr(
        embedding_model_artifacts,
        "stream_cached_embedding_model_artifacts",
        cache_miss,
    )
    monkeypatch.setattr(
        embedding_model_artifacts,
        "stream_embedding_model_artifacts",
        acquisition_is_forbidden,
    )
    monkeypatch.delenv("ORT_LOAD_CONFIG_FROM_MODEL", raising=False)
    monkeypatch.delenv(
        "SERVICE_RAG_EMBEDDING_ORT_LOAD_CONFIG_FROM_MODEL", raising=False
    )
    return calls


def test_partial_cache_blocks_parity_and_closes_without_finishing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_tools, _ = _native_test_tools(monkeypatch)
    cache = _partial_cache(tmp_path)
    calls = _configure_read_only_cache_miss(monkeypatch)
    builder = _RuntimeBuilder()

    with pytest.raises(
        runtime_tools.FastEmbedCacheUnavailableError,
        match="complete model snapshot required for offline probe",
    ):
        runtime_tools.bootstrap_cached_fastembed_runtime(
            _NativeModule(builder),
            cache,
            threads=4,
        )

    assert len(calls) == 1
    assert calls[0][0] == str(cache.resolve())
    assert calls[0][2] is builder
    assert builder.begin_asset_calls == []
    assert builder.write_chunk_calls == 0
    assert builder.asset_verified_calls == []
    assert builder.finish_calls == 0
    assert builder.close_calls == 1


def test_perf_marks_partial_cache_not_run_and_closes_builder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, perf_tools = _native_test_tools(monkeypatch)
    cache = _partial_cache(tmp_path)
    monkeypatch.setenv("ALEXANDRIA_FASTEMBED_PARITY_CACHE", str(cache))
    _configure_read_only_cache_miss(monkeypatch)
    builder = _RuntimeBuilder()

    report = perf_tools._measure_inference_if_cached(_NativeModule(builder))

    assert report["status"] == "not_run"
    assert report["reason"] == "model_cache_incomplete"
    assert builder.finish_calls == 0
    assert builder.close_calls == 1


def test_perf_does_not_hide_cache_corruption_as_not_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, perf_tools = _native_test_tools(monkeypatch)
    cache = _partial_cache(tmp_path)
    monkeypatch.setenv("ALEXANDRIA_FASTEMBED_PARITY_CACHE", str(cache))
    _configure_read_only_cache_miss(monkeypatch)
    builder = _RuntimeBuilder()

    def cache_corruption(
        cache_dir: str | None,
        config: object,
        sink: object,
    ) -> None:
        raise ValueError("corrupt cache evidence")

    monkeypatch.setattr(
        embedding_model_artifacts,
        "stream_cached_embedding_model_artifacts",
        cache_corruption,
    )

    with pytest.raises(ValueError, match="corrupt cache evidence"):
        perf_tools._measure_inference_if_cached(_NativeModule(builder))

    assert builder.finish_calls == 0
    assert builder.close_calls == 1
