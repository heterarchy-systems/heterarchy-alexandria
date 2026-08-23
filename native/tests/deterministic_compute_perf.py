"""Measure real release-FFI performance for deterministic Rust compute authorities."""

from __future__ import annotations

import importlib.util
import json
import os
import statistics
import sysconfig
import tempfile
import time
import tomllib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPOSITORY_ROOT / "native/feature_authority.toml"
MODULE_NAME = "heterarchy_alexandria_native"
FEATURES = (
    "document_analysis",
    "chunking",
    "link_extraction",
    "fingerprint",
    "graph_compute",
)
SAMPLE_COUNT = 7
WARMUP_COUNT = 2


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class NativeModule(Protocol):
    """Native extension surface benchmarked by this authority gate."""

    def compute_contract_version(self) -> int: ...

    def analyze_document_batch_json(self, payload: bytes) -> bytes: ...

    def chunk_markdown_batch_json(self, payload: bytes) -> bytes: ...

    def extract_reference_batch_json(self, payload: bytes) -> bytes: ...

    def compute_hash_batch_json(self, payload: bytes) -> bytes: ...

    def compute_graph_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    report_path = _required_path("HETERARCHY_ALEXANDRIA_DETERMINISTIC_PERF_REPORT")
    registry = _load_registry()
    corpora = {
        feature: _load_feature_corpus(registry, feature) for feature in FEATURES
    }
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-deterministic-perf-"
    ) as directory:
        native = _load_native_module(Path(directory))
        if native.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        feature_reports = {
            "document_analysis": _measure_feature(
                native.analyze_document_batch_json,
                _document_payloads(corpora["document_analysis"]),
            ),
            "chunking": _measure_feature(
                native.chunk_markdown_batch_json,
                _chunking_payloads(corpora["chunking"]),
            ),
            "link_extraction": _measure_feature(
                native.extract_reference_batch_json,
                _reference_payloads(corpora["link_extraction"]),
            ),
            "fingerprint": _measure_feature(
                native.compute_hash_batch_json,
                _hash_payloads(corpora["fingerprint"]),
            ),
            "graph_compute": _measure_feature(
                native.compute_graph_json,
                _graph_payloads(corpora["graph_compute"]),
            ),
        }

    report: dict[str, JsonValue] = {
        "schema_version": 1,
        "benchmark": "deterministic_compute_real_ffi",
        "authority": "rust",
        "features": cast(dict[str, JsonValue], feature_reports),
        "interpretation": [
            "Every measurement calls the release native extension through the production JSON FFI boundary.",
            "Inputs are immutable accepted corpora; no retired Python compute implementation is executed.",
            "The gate records steady-state call latency and byte throughput without weakening functional parity gates.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "deterministic-compute-perf: PASS "
        f"features={list(feature_reports)} report={report_path}"
    )
    return 0


def _measure_feature(
    operation: Callable[[bytes], bytes],
    payloads: list[bytes],
) -> dict[str, JsonValue]:
    if not payloads:
        raise AssertionError("performance feature must contain at least one payload")
    scenarios: list[JsonValue] = []
    for index, payload in enumerate(payloads):
        response = operation(payload)
        _validate_response(response)
        iterations = _iteration_count(len(payload))
        for _ in range(WARMUP_COUNT):
            _consume_bytes(operation(payload))
        samples: list[int] = []
        response_bytes = len(response)
        for _ in range(SAMPLE_COUNT):
            started = time.perf_counter_ns()
            accumulator = 0
            for _ in range(iterations):
                accumulator ^= len(operation(payload))
            elapsed = time.perf_counter_ns() - started
            _consume_integer(accumulator)
            samples.append(elapsed // iterations)
        median_ns = float(statistics.median(samples))
        if median_ns <= 0.0:
            raise AssertionError("native FFI timing must be positive")
        seconds = median_ns / 1_000_000_000.0
        scenarios.append(
            {
                "scenario_index": index,
                "iterations_per_sample": iterations,
                "samples": SAMPLE_COUNT,
                "request_bytes": len(payload),
                "response_bytes": response_bytes,
                "median_milliseconds": round(median_ns / 1_000_000.0, 6),
                "calls_per_second": round(1.0 / seconds, 3),
                "request_megabytes_per_second": round(
                    (len(payload) / 1_000_000.0) / seconds,
                    3,
                ),
            }
        )
    return {
        "status": "measured",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }


def _document_payloads(corpus: dict[str, JsonValue]) -> list[bytes]:
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    return [
        _encode(
            {
                "contract_version": 1,
                "documents": [
                    {
                        "document_id": _require_string(case, "case_id"),
                        "relative_path": _require_string(case, "relative_path"),
                        "text": _require_string(case, "text"),
                    }
                    for case in cases
                ],
            }
        )
    ]


def _chunking_payloads(corpus: dict[str, JsonValue]) -> list[bytes]:
    grouped: dict[tuple[int, int], list[dict[str, JsonValue]]] = defaultdict(list)
    for value in _require_list(corpus, "cases"):
        case = _require_object(value)
        grouped[
            (
                _require_int(case, "max_chars"),
                _require_int(case, "overlap_chars"),
            )
        ].append(case)
    return [
        _encode(
            {
                "contract_version": 1,
                "chunking_version": 1,
                "max_chars": max_chars,
                "overlap_chars": overlap_chars,
                "documents": [
                    {
                        "document_id": _require_string(case, "case_id"),
                        "relative_path": _require_string(case, "relative_path"),
                        "title": _require_string(case, "title"),
                        "content": _require_string(case, "content"),
                    }
                    for case in cases
                ],
            }
        )
        for (max_chars, overlap_chars), cases in sorted(grouped.items())
    ]


def _reference_payloads(corpus: dict[str, JsonValue]) -> list[bytes]:
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    return [
        _encode(
            {
                "contract_version": 1,
                "extraction_version": 1,
                "documents": [
                    {
                        "note_id": _require_string(case, "note_id"),
                        "relative_path": _require_string(case, "relative_path"),
                        "alexandria_root": _require_string(case, "alexandria_root"),
                        "body": _require_string(case, "body"),
                        "frontmatter_edges": _require_list(case, "frontmatter_edges"),
                    }
                    for case in cases
                ],
            }
        )
    ]


def _hash_payloads(corpus: dict[str, JsonValue]) -> list[bytes]:
    cases = [_require_object(value) for value in _require_list(corpus, "cases")]
    return [
        _encode(
            {
                "contract_version": 1,
                "hashing_version": 1,
                "documents": [
                    {
                        "document_id": _require_string(case, "document_id"),
                        "relative_path": _require_string(case, "relative_path"),
                        "text": _require_string(case, "text"),
                        "embedding_fingerprint": case.get("embedding_fingerprint"),
                        "indexed_at": case.get("indexed_at"),
                        "previous": case.get("previous"),
                        "current_chunk_identities": case.get(
                            "current_chunk_identities"
                        ),
                        "current_edge_identities": case.get(
                            "current_edge_identities"
                        ),
                    }
                    for case in cases
                ],
            }
        )
    ]


def _graph_payloads(corpus: dict[str, JsonValue]) -> list[bytes]:
    return [
        _encode(
            {
                "contract_version": 1,
                "graph_compute_version": 1,
                "batch_size": _require_int(case, "batch_size"),
                "source_notes": _require_list(case, "source_notes"),
                "source_edges": _require_list(case, "source_edges"),
                "previous_projection": case.get("previous_projection"),
                "traversal_requests": _require_list(case, "traversal_requests"),
                "lineage_requests": _require_list(case, "lineage_requests"),
            }
        )
        for case in (
            _require_object(value) for value in _require_list(corpus, "cases")
        )
    ]


def _load_registry() -> dict[str, object]:
    return cast(dict[str, object], tomllib.loads(REGISTRY_PATH.read_text(encoding="utf-8")))


def _load_feature_corpus(
    registry: dict[str, object],
    feature: str,
) -> dict[str, JsonValue]:
    features = registry.get("features")
    if not isinstance(features, dict):
        raise TypeError("authority registry features must be an object")
    config = features.get(feature)
    if not isinstance(config, dict):
        raise TypeError(f"missing authority registry feature: {feature}")
    corpora = config.get("golden_corpora")
    if not isinstance(corpora, list) or not corpora or not isinstance(corpora[0], str):
        raise TypeError(f"feature {feature} has no golden corpus")
    path = REPOSITORY_ROOT / corpora[0]
    return _require_object(cast(JsonValue, json.loads(path.read_text(encoding="utf-8"))))


def _load_native_module(temp_root: Path) -> NativeModule:
    library = _required_path("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix, str) or not suffix:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    destination = temp_root / f"{MODULE_NAME}{suffix}"
    destination.write_bytes(library.read_bytes())
    specification = importlib.util.spec_from_file_location(MODULE_NAME, destination)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load native extension from {destination}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    if not isinstance(module, ModuleType):
        raise RuntimeError("native extension loader returned an invalid module")
    if Path(str(module.__file__)).resolve() != destination.resolve():
        raise RuntimeError("native extension provenance mismatch")
    return cast(NativeModule, module)


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"required environment path is missing: {name}")
    path = Path(value).resolve()
    if name.endswith("NATIVE_LIBRARY") and not path.is_file():
        raise FileNotFoundError(f"native extension artifact is missing: {path}")
    return path


def _iteration_count(payload_bytes: int) -> int:
    if payload_bytes <= 10_000:
        return 250
    if payload_bytes <= 100_000:
        return 75
    return 20


def _validate_response(value: bytes) -> None:
    decoded = cast(JsonValue, json.loads(value))
    if not isinstance(decoded, dict) or decoded.get("contract_version") != 1:
        raise AssertionError("native performance response contract drifted")


def _consume_bytes(value: bytes) -> None:
    if not value:
        raise AssertionError("native performance response must not be empty")


def _consume_integer(value: int) -> None:
    if value < 0:
        raise AssertionError("unreachable negative performance accumulator")


def _encode(value: dict[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _require_object(value: JsonValue) -> dict[str, JsonValue]:
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


def _require_int(value: dict[str, JsonValue], key: str) -> int:
    candidate = value.get(key)
    if not isinstance(candidate, int) or isinstance(candidate, bool):
        raise TypeError(f"expected JSON integer at {key}")
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())
