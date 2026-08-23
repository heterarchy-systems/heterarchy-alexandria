"""Numerical parity between frozen pre-cutover FastEmbed evidence and Rust."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import sysconfig
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NATIVE_TARGET = REPOSITORY_ROOT / "native" / "target"
DEFAULT_CACHE_DIR = NATIVE_TARGET / "fastembed-parity-cache"
CORPUS_PATH = (
    REPOSITORY_ROOT
    / "native/corpora/bulk_embedding/v1/python_fastembed_numerical_baseline.json"
)
MODULE_NAME = "heterarchy_alexandria_native"
THREADS = 4
BATCH_SIZE = 16
RUST_FASTEMBED_VERSION = "5.17.4"
EXPECTED_MODEL = "intfloat/multilingual-e5-small"
EXPECTED_PROVIDER = "FASTEMBED_LOCAL"
EXPECTED_DIMENSIONS = 384
MAX_ABSOLUTE_DIFFERENCE = 1e-4
MIN_COSINE_SIMILARITY = 0.99999


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Narrow native extension surface used by this numerical gate."""

    def compute_contract_version(self) -> int: ...

    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...

    def embed_multilingual_e5_query(
        self,
        query_input: str,
        cache_directory: str | None,
        threads: int,
    ) -> list[float]: ...


def main() -> int:
    cache_dir = Path(
        os.environ.get("ALEXANDRIA_FASTEMBED_PARITY_CACHE", str(DEFAULT_CACHE_DIR))
    ).resolve()
    if not _directory_has_files(cache_dir):
        raise RuntimeError(
            "frozen FastEmbed numerical parity requires the local multilingual-e5-small cache"
        )
    corpus = _load_json_object(CORPUS_PATH)
    provider = _require_object(corpus, "provider")
    _validate_frozen_provider(provider)
    documents = [_require_object_value(value) for value in _require_list(corpus, "documents")]
    queries = [_require_object_value(value) for value in _require_list(corpus, "queries")]
    frozen_document_vectors = [_require_float_list(case.get("vector")) for case in documents]
    frozen_query_vectors = [_require_float_list(case.get("vector")) for case in queries]

    with tempfile.TemporaryDirectory(prefix="heterarchy-fastembed-parity-") as directory:
        native_module = _load_native_module(Path(directory))
        native_document_vectors = _native_document_vectors(
            native_module,
            documents,
            provider=provider,
            cache_dir=cache_dir,
        )
        native_query_vectors = _native_query_vectors(
            native_module,
            queries,
            cache_dir=cache_dir,
        )

    document_metrics = _compare_vectors(
        frozen_document_vectors,
        native_document_vectors,
    )
    query_metrics = _compare_vectors(frozen_query_vectors, native_query_vectors)
    print(
        "fastembed-frozen-numerical-parity: PASS "
        f"document_cases={len(documents)} query_cases={len(queries)} "
        f"dimensions={EXPECTED_DIMENSIONS} "
        f"document_max_abs_diff={document_metrics['max_abs_diff']:.8g} "
        f"document_min_cosine={document_metrics['min_cosine']:.10f} "
        f"query_max_abs_diff={query_metrics['max_abs_diff']:.8g} "
        f"query_min_cosine={query_metrics['min_cosine']:.10f}"
    )
    return 0


def _validate_frozen_provider(provider: dict[str, JsonValue]) -> None:
    if _require_string(provider, "provider_name") != EXPECTED_PROVIDER:
        raise AssertionError("frozen embedding provider identity drift")
    if _require_string(provider, "model_name") != EXPECTED_MODEL:
        raise AssertionError("frozen embedding model identity drift")
    if _require_int(provider, "dimensions") != EXPECTED_DIMENSIONS:
        raise AssertionError("frozen embedding dimension drift")
    if _require_string(provider, "pooling_mode") != "mean":
        raise AssertionError("frozen embedding pooling drift")
    if provider.get("normalize") is not True:
        raise AssertionError("frozen embedding normalization drift")
    if not _require_string(provider, "document_input_format").endswith(
        "+e5-passage-prefix-v1"
    ):
        raise AssertionError("frozen embedding document input format drift")


def _native_document_vectors(
    native_module: NativeModule,
    documents: list[dict[str, JsonValue]],
    *,
    provider: dict[str, JsonValue],
    cache_dir: Path,
) -> list[list[float]]:
    if native_module.compute_contract_version() != 1:
        raise AssertionError("native compute contract version must be 1")
    request: dict[str, JsonValue] = {
        "contract_version": 1,
        "embedding_version": 1,
        "runtime": {
            "cache_directory": str(cache_dir),
            "threads": THREADS,
        },
        "request": {
            "model": {
                "provider": EXPECTED_PROVIDER,
                "model": EXPECTED_MODEL,
                "provider_version": RUST_FASTEMBED_VERSION,
                "pooling_mode": "mean",
                "normalize": True,
                "dimensions": EXPECTED_DIMENSIONS,
                "document_input_format": _require_string(
                    provider, "document_input_format"
                ),
                "input_kind": "e5_passage",
            },
            "batch_size": BATCH_SIZE,
            "documents": [
                {
                    "item_id": _require_string(case, "case_id"),
                    "content": _require_string(case, "content"),
                    "title": _optional_string(case, "title"),
                    "heading": _optional_string(case, "heading"),
                }
                for case in documents
            ],
        },
    }
    response = _load_json_bytes(native_module.run_bulk_embedding_batch_json(_encode(request)))
    records = _require_list(response, "records")
    if len(records) != len(documents):
        raise AssertionError("native embedding record cardinality mismatch")
    vectors: list[list[float]] = []
    for expected_index, raw_record in enumerate(records):
        record = _require_object_value(raw_record)
        if _require_int(record, "input_index") != expected_index:
            raise AssertionError("native embedding record order drift")
        vectors.append(_require_float_list(record.get("vector")))
    return vectors


def _native_query_vectors(
    native_module: NativeModule,
    queries: list[dict[str, JsonValue]],
    *,
    cache_dir: Path,
) -> list[list[float]]:
    return [
        [
            float(value)
            for value in native_module.embed_multilingual_e5_query(
                f"query: {_require_string(case, 'query').strip()}",
                str(cache_dir),
                THREADS,
            )
        ]
        for case in queries
    ]


def _compare_vectors(
    frozen_vectors: list[list[float]],
    native_vectors: list[list[float]],
) -> dict[str, float]:
    if len(frozen_vectors) != len(native_vectors):
        raise AssertionError("embedding implementation cardinality mismatch")
    max_abs_diff = 0.0
    min_cosine = 1.0
    for index, (frozen_vector, native_vector) in enumerate(
        zip(frozen_vectors, native_vectors, strict=True)
    ):
        if len(frozen_vector) != len(native_vector):
            raise AssertionError(f"case {index}: embedding dimension mismatch")
        if len(native_vector) != EXPECTED_DIMENSIONS:
            raise AssertionError(
                f"case {index}: expected {EXPECTED_DIMENSIONS} dimensions"
            )
        abs_diff = max(
            abs(frozen_value - native_value)
            for frozen_value, native_value in zip(
                frozen_vector,
                native_vector,
                strict=True,
            )
        )
        cosine = _cosine_similarity(frozen_vector, native_vector)
        max_abs_diff = max(max_abs_diff, abs_diff)
        min_cosine = min(min_cosine, cosine)
        if abs_diff > MAX_ABSOLUTE_DIFFERENCE:
            raise AssertionError(
                f"case {index}: max absolute difference {abs_diff} exceeds "
                f"{MAX_ABSOLUTE_DIFFERENCE}"
            )
        if cosine < MIN_COSINE_SIMILARITY:
            raise AssertionError(
                f"case {index}: cosine similarity {cosine} below "
                f"{MIN_COSINE_SIMILARITY}"
            )
        native_norm = math.sqrt(sum(value * value for value in native_vector))
        if abs(native_norm - 1.0) > 1e-4:
            raise AssertionError(f"case {index}: native vector is not normalized")
    return {"max_abs_diff": max_abs_diff, "min_cosine": min_cosine}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _load_native_module(temp_root: Path) -> NativeModule:
    library = _native_library_path()
    suffix_value = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix_value, str) or not suffix_value:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    destination = temp_root / f"{MODULE_NAME}{suffix_value}"
    shutil.copy2(library, destination)
    specification = importlib.util.spec_from_file_location(MODULE_NAME, destination)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load native extension from {destination}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    if not isinstance(module, ModuleType):
        raise RuntimeError("native extension loader returned an invalid module")
    loaded_path = Path(str(module.__file__)).resolve()
    if loaded_path != destination.resolve():
        raise RuntimeError(f"native provenance mismatch: loaded {loaded_path}")
    return cast(NativeModule, module)


def _native_library_path() -> Path:
    configured = os.environ.get("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    if configured:
        path = Path(configured).resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured native library does not exist: {path}")
    target = REPOSITORY_ROOT / "native/target/debug"
    for name in (
        "libheterarchy_alexandria_native.dylib",
        "libheterarchy_alexandria_native.so",
        "heterarchy_alexandria_native.dll",
    ):
        candidate = target / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"native extension artifact is missing under {target}")


def _directory_has_files(directory: Path) -> bool:
    return directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))


def _encode(value: dict[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _load_json_object(path: Path) -> dict[str, JsonValue]:
    value = cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))
    return _require_object_value(value)


def _load_json_bytes(value: bytes) -> dict[str, JsonValue]:
    return _require_object_value(cast(JsonValue, json.loads(value)))


def _require_object(
    value: dict[str, JsonValue],
    key: str,
) -> dict[str, JsonValue]:
    return _require_object_value(value.get(key))


def _require_object_value(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError("expected JSON object")
    return value


def _require_list(value: dict[str, JsonValue], key: str) -> list[JsonValue]:
    candidate = value.get(key)
    if not isinstance(candidate, list):
        raise TypeError(f"expected JSON list at {key}")
    return candidate


def _require_string(value: dict[str, JsonValue], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str):
        raise TypeError(f"expected JSON string at {key}")
    return candidate


def _optional_string(value: dict[str, JsonValue], key: str) -> str | None:
    candidate = value.get(key)
    if candidate is None or isinstance(candidate, str):
        return candidate
    raise TypeError(f"expected optional JSON string at {key}")


def _require_int(value: dict[str, JsonValue], key: str) -> int:
    candidate = value.get(key)
    if not isinstance(candidate, int) or isinstance(candidate, bool):
        raise TypeError(f"expected JSON integer at {key}")
    return candidate


def _require_float_list(value: JsonValue) -> list[float]:
    if not isinstance(value, list):
        raise TypeError("expected vector list")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise TypeError("expected numeric vector value")
        result.append(float(item))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
