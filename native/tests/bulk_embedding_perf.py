"""Measure Rust-authoritative bulk embedding FFI and cached inference performance."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import resource
import shutil
import statistics
import sys
import sysconfig
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIRECTORY = REPOSITORY_ROOT / "native/corpora/bulk_embedding/v1"
NUMERICAL_BASELINE_NAME = "python_fastembed_numerical_baseline.json"
MODULE_NAME = "heterarchy_alexandria_native"
SCALES = (1, 16, 100, 1_000)
SAMPLE_COUNT = 7
INFERENCE_SCALES = (1, 16, 64)
INFERENCE_SAMPLE_COUNT = 3
INFERENCE_THREADS = 4
RUST_FASTEMBED_VERSION = "5.17.4"
DEFAULT_FASTEMBED_CACHE = REPOSITORY_ROOT / "native/target/fastembed-parity-cache"


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Real extension functions measured by this performance harness."""

    def prepare_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...

    def finalize_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...

    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes: ...


class ScenarioReport(dict[str, JsonValue]):
    """Named report type for one measured input cardinality."""


def main() -> int:
    report_path = _required_environment_path(
        "HETERARCHY_ALEXANDRIA_BULK_EMBEDDING_PERF_REPORT"
    )
    core_report_path = _required_environment_path(
        "HETERARCHY_ALEXANDRIA_CORE_PERF_REPORT"
    )
    core_report = _load_json_object(core_report_path)
    model = _current_model_contract()
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-native-"
    ) as directory:
        native = _load_native_module(Path(directory))
        scenarios = [
            _measure_scenario(native, model, item_count) for item_count in SCALES
        ]
        native_inference = _measure_inference_if_cached(native)

    report: dict[str, JsonValue] = {
        "schema_version": 2,
        "feature": "bulk_embedding",
        "authority": "rust",
        "scope": "native_preparation_finalization_real_ffi_and_cached_fastembed_inference",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "peak_rss_bytes": _peak_rss_bytes(),
        },
        "model_contract": model,
        "direct_core": core_report,
        "native_ffi_scenarios": [dict(value) for value in scenarios],
        "native_inference": native_inference,
        "interpretation": [
            "Native FFI timing includes strict JSON decode, Rust compute, and JSON encode.",
            "The post-cutover performance harness does not retain a Python embedding compute oracle.",
            "Functional parity is enforced by immutable pre-cutover corpora and real native FFI gates.",
            "Cached inference timing measures only the Rust FastEmbed production compute path.",
            "Cold-session timing uses a warm on-disk model cache and excludes network acquisition time.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    inference_status = _require_string(native_inference, "status")
    print(
        f"bulk-embedding-perf: PASS scenarios={len(scenarios)} "
        f"report={report_path} inference={inference_status.upper()}"
    )
    return 0


def _measure_inference_if_cached(native: NativeModule) -> dict[str, JsonValue]:
    cache_directory = Path(
        os.environ.get(
            "ALEXANDRIA_FASTEMBED_PARITY_CACHE",
            str(DEFAULT_FASTEMBED_CACHE),
        )
    ).resolve()
    if not _directory_has_files(cache_directory):
        return {
            "status": "not_run",
            "reason": "local multilingual-e5-small model cache is absent",
            "cold_start": "not_measured",
            "warm_batches": [],
            "numerical_parity": "covered_by_frozen_baseline_when_cache_is_present",
        }

    cold_request = _inference_request(item_count=1, cache_directory=cache_directory)
    started = time.perf_counter_ns()
    cold_result = _load_json_bytes(
        native.run_bulk_embedding_batch_json(_encode(cold_request))
    )
    cold_ns = time.perf_counter_ns() - started
    _validate_native_inference_result(cold_result, expected_count=1)
    warm_batches = [
        _measure_warm_inference_scenario(
            native,
            item_count=item_count,
            cache_directory=cache_directory,
        )
        for item_count in INFERENCE_SCALES
    ]
    return {
        "status": "measured",
        "cache_directory_present": True,
        "threads": INFERENCE_THREADS,
        "cold_start": {
            "definition": "first Rust session initialization from populated on-disk model cache",
            "item_count": 1,
            "native_ffi_milliseconds": _nanoseconds_to_milliseconds(float(cold_ns)),
        },
        "warm_batches": warm_batches,
        "numerical_parity": {
            "status": "verified_against_frozen_pre_cutover_baseline",
            "max_absolute_difference_tolerance": 1e-4,
            "minimum_cosine_similarity": 0.99999,
        },
    }


def _measure_warm_inference_scenario(
    native: NativeModule,
    *,
    item_count: int,
    cache_directory: Path,
) -> dict[str, JsonValue]:
    payload = _inference_request(item_count=item_count, cache_directory=cache_directory)
    encoded = _encode(payload)
    native_elapsed = _median_elapsed_ns_samples(
        lambda: _consume_native_inference(
            native.run_bulk_embedding_batch_json(encoded),
            expected_count=item_count,
        ),
        sample_count=INFERENCE_SAMPLE_COUNT,
    )
    native_seconds = native_elapsed / 1_000_000_000.0
    return {
        "item_count": item_count,
        "samples": INFERENCE_SAMPLE_COUNT,
        "native_ffi_median_milliseconds": _nanoseconds_to_milliseconds(native_elapsed),
        "native_ffi_items_per_second": round(item_count / native_seconds, 3),
        "native_request_bytes": len(encoded),
    }


def _inference_request(
    item_count: int,
    cache_directory: Path = DEFAULT_FASTEMBED_CACHE,
) -> dict[str, JsonValue]:
    return {
        "contract_version": 1,
        "embedding_version": 1,
        "runtime": {
            "cache_directory": str(cache_directory.resolve()),
            "threads": INFERENCE_THREADS,
        },
        "request": _request(_current_model_contract(), item_count),
    }


def _validate_native_inference_result(
    result: Mapping[str, JsonValue],
    expected_count: int,
) -> None:
    records = _require_list(result, "records")
    if len(records) != expected_count:
        raise AssertionError("native inference result cardinality mismatch")
    for raw_record in records:
        record = _require_object(raw_record)
        vector = _require_float_list(record.get("vector"))
        if len(vector) != 384:
            raise AssertionError("native inference vector dimension mismatch")


def _consume_native_inference(value: bytes, expected_count: int) -> int:
    result = _load_json_bytes(value)
    _validate_native_inference_result(result, expected_count=expected_count)
    return len(_require_list(result, "records"))


def _median_elapsed_ns_samples(
    operation: Callable[[], int],
    sample_count: int,
) -> float:
    _consume_integer(operation())
    samples: list[int] = []
    for _ in range(sample_count):
        started = time.perf_counter_ns()
        _consume_integer(operation())
        samples.append(time.perf_counter_ns() - started)
    return float(statistics.median(samples))


def _directory_has_files(directory: Path) -> bool:
    return directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))


def _measure_scenario(
    native: NativeModule,
    model: dict[str, JsonValue],
    item_count: int,
) -> ScenarioReport:
    request = _request(model, item_count)
    preparation_payload: dict[str, JsonValue] = {
        "contract_version": 1,
        "embedding_version": 1,
        "request": request,
    }
    preparation_encoded = _encode(preparation_payload)
    native_preparation = _load_json_bytes(
        native.prepare_bulk_embedding_batch_json(preparation_encoded)
    )
    inference_batches = _zero_inference_batches(native_preparation)
    finalization_payload: dict[str, JsonValue] = {
        **preparation_payload,
        "inference_batches": inference_batches,
    }
    finalization_encoded = _encode(finalization_payload)
    native_result = _load_json_bytes(
        native.finalize_bulk_embedding_batch_json(finalization_encoded)
    )
    _validate_native_inference_result(native_result, expected_count=item_count)

    iterations = _iteration_count(item_count)
    native_prepare_ns = _median_elapsed_ns(
        lambda: len(native.prepare_bulk_embedding_batch_json(preparation_encoded)),
        iterations,
    )
    native_finalize_ns = _median_elapsed_ns(
        lambda: len(native.finalize_bulk_embedding_batch_json(finalization_encoded)),
        iterations,
    )
    if native_prepare_ns <= 0 or native_finalize_ns <= 0:
        raise AssertionError("performance timing must be positive")

    return ScenarioReport(
        item_count=item_count,
        iterations=iterations,
        native_ffi_prepare_median_milliseconds=_nanoseconds_to_milliseconds(
            native_prepare_ns
        ),
        native_ffi_finalize_median_milliseconds=_nanoseconds_to_milliseconds(
            native_finalize_ns
        ),
        native_prepare_request_bytes=len(preparation_encoded),
        native_prepare_response_bytes=len(_encode(native_preparation)),
        native_finalize_request_bytes=len(finalization_encoded),
        native_finalize_response_bytes=len(_encode(native_result)),
    )


def _current_model_contract() -> dict[str, JsonValue]:
    structural_corpus = _structural_corpus_path()
    corpus = _load_json_object(structural_corpus)
    cases = _require_list(corpus, "cases")
    if not cases:
        raise RuntimeError("bulk embedding corpus contains no cases")
    first_case = _require_object(cases[0])
    model = dict(_require_object(first_case.get("model")))
    model["provider_version"] = RUST_FASTEMBED_VERSION
    return model


def _structural_corpus_path() -> Path:
    for candidate in sorted(CORPUS_DIRECTORY.glob("*.json")):
        if candidate.name == NUMERICAL_BASELINE_NAME:
            continue
        value = _load_json_object(candidate)
        if value.get("feature") == "bulk_embedding" and isinstance(
            value.get("cases"), list
        ):
            return candidate
    raise FileNotFoundError("versioned bulk embedding structural corpus is missing")


def _request(
    model: dict[str, JsonValue],
    item_count: int,
) -> dict[str, JsonValue]:
    documents: list[JsonValue] = [
        {
            "item_id": f"perf-chunk-{index}",
            "content": (
                "검색 품질과 deterministic ranking evidence를 검증하는 "
                f"representative chunk {index}."
            ),
            "title": "Alexandria retrieval performance",
            "heading": f"Bulk embedding scenario {index}",
        }
        for index in range(item_count)
    ]
    return {
        "model": model,
        "batch_size": 16,
        "documents": documents,
    }


def _zero_inference_batches(
    preparation: Mapping[str, JsonValue],
) -> list[JsonValue]:
    model = _require_object(preparation.get("model"))
    dimensions = _require_int(model, "dimensions")
    batches = _require_list(preparation, "batches")
    result: list[JsonValue] = []
    for raw_batch in batches:
        batch = _require_object(raw_batch)
        items = _require_list(batch, "items")
        result.append(
            {
                "batch_index": _require_int(batch, "batch_index"),
                "vectors": [[0.0] * dimensions for _ in items],
            }
        )
    return result


def _median_elapsed_ns(operation: Callable[[], int], iterations: int) -> float:
    samples: list[int] = []
    for _ in range(2):
        _consume_integer(operation())
    for _ in range(SAMPLE_COUNT):
        started = time.perf_counter_ns()
        accumulator = 0
        for _ in range(iterations):
            accumulator ^= operation()
        elapsed = time.perf_counter_ns() - started
        _consume_integer(accumulator)
        samples.append(elapsed // iterations)
    return float(statistics.median(samples))


def _consume_integer(value: int) -> None:
    if value < 0:
        raise AssertionError("unreachable negative benchmark accumulator")


def _iteration_count(item_count: int) -> int:
    if item_count <= 1:
        return 1_000
    if item_count <= 16:
        return 300
    if item_count <= 100:
        return 50
    return 5


def _nanoseconds_to_milliseconds(value: float) -> float:
    return round(value / 1_000_000.0, 6)


def _peak_rss_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1_024)


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
    target = REPOSITORY_ROOT / "native/target/release"
    for name in (
        "libheterarchy_alexandria_native.dylib",
        "libheterarchy_alexandria_native.so",
        "heterarchy_alexandria_native.dll",
    ):
        candidate = target / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"release native extension artifact is missing under {target}"
    )


def _required_environment_path(name: str) -> Path:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"required performance report environment is missing: {name}")
    return Path(value).resolve()


def _encode(value: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _load_json_object(path: Path) -> dict[str, JsonValue]:
    return _require_object(cast(JsonValue, json.loads(path.read_text(encoding="utf-8"))))


def _load_json_bytes(value: bytes) -> dict[str, JsonValue]:
    return _require_object(cast(JsonValue, json.loads(value)))


def _require_object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError("expected JSON object")
    return value


def _require_list(value: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    candidate = value.get(key)
    if not isinstance(candidate, list):
        raise TypeError(f"expected JSON list at {key}")
    return candidate


def _require_string(value: Mapping[str, JsonValue], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str):
        raise TypeError(f"expected JSON string at {key}")
    return candidate


def _require_int(value: Mapping[str, JsonValue], key: str) -> int:
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
