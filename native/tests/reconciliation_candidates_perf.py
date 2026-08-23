"""Measure Rust-authoritative reconciliation candidate scaling through real PyO3."""

from __future__ import annotations

import importlib.util
import json
import os
import resource
import shutil
import sys
import sysconfig
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
CORE_REPORT_PATH = Path(
    os.environ.get(
        "HETERARCHY_ALEXANDRIA_RECONCILIATION_CORE_PERF_REPORT",
        REPOSITORY_ROOT / "native/perf/evidence/reconciliation_candidates_core_v1.json",
    )
)
COMBINED_REPORT_PATH = Path(
    os.environ.get(
        "HETERARCHY_ALEXANDRIA_RECONCILIATION_PERF_REPORT",
        REPOSITORY_ROOT / "native/perf/evidence/reconciliation_candidates_combined_v1.json",
    )
)
MODULE_NAME = "heterarchy_alexandria_native"
BLOCK_SIZE = 8
VECTOR_DIMENSIONS = 8
SCALES = (1_000, 10_000, 100_000)

sys.path.insert(0, str(BACKEND_ROOT))


class NativeModule(Protocol):
    def compute_reconciliation_candidates_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    native = _native_module()
    scenarios: list[dict[str, object]] = []
    for item_count in SCALES:
        items = _synthetic_items(item_count)
        policy: dict[str, object] = {
            "vector_similarity_threshold": 0.99,
            "graph_similarity_threshold": 0.99,
            "max_block_size": BLOCK_SIZE,
            "max_candidates_per_item": 4,
        }
        payload = _encode(
            {
                "contract_version": 1,
                "candidate_version": 1,
                "policy": policy,
                "items": items,
            }
        )
        rss_before = _peak_rss_bytes()
        native_started = perf_counter()
        encoded = native.compute_reconciliation_candidates_json(payload)
        native_seconds = perf_counter() - native_started
        rss_after = _peak_rss_bytes()
        actual = _load_object(encoded)
        metrics = actual.get("metrics")
        if not isinstance(metrics, dict):
            raise TypeError("native candidate metrics must be an object")
        comparisons = metrics.get("comparison_pairs")
        retained = metrics.get("retained_pairs")
        if not isinstance(comparisons, int) or not isinstance(retained, int):
            raise TypeError("native candidate metrics must contain integer pair counts")
        if metrics.get("input_items") != item_count:
            raise AssertionError("native candidate input cardinality metric drifted")
        if comparisons > item_count * BLOCK_SIZE:
            raise AssertionError(
                "native candidate comparison work exceeded the bounded blocking budget"
            )
        if retained > item_count * 4:
            raise AssertionError(
                "native candidate retained pairs exceeded the per-item candidate budget"
            )
        if native_seconds <= 0.0:
            raise AssertionError("native candidate timing must be positive")
        scenarios.append(
            {
                "item_count": item_count,
                "input_json_bytes": len(payload),
                "output_json_bytes": len(encoded),
                "native_ffi_milliseconds": native_seconds * 1_000.0,
                "native_items_per_second": item_count / native_seconds,
                "comparison_pairs": comparisons,
                "retained_pairs": retained,
                "peak_rss_before_bytes": rss_before,
                "peak_rss_after_bytes": rss_after,
                "peak_rss_growth_bytes": max(0, rss_after - rss_before),
            }
        )

    report = {
        "schema_version": 2,
        "benchmark": "reconciliation_candidates_real_ffi",
        "authority": "rust",
        "profile": "release",
        "block_size": BLOCK_SIZE,
        "vector_dimensions": VECTOR_DIMENSIONS,
        "core_report": _load_object(CORE_REPORT_PATH.read_bytes()),
        "scenarios": scenarios,
        "interpretation": [
            "Rust is the sole candidate-compute authority after cutover.",
            "The harness validates bounded comparison work instead of retaining a Python compute oracle.",
            "Functional parity remains enforced by the immutable pre-cutover corpus and real native FFI gate.",
        ],
    }
    COMBINED_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMBINED_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"reconciliation-candidate-perf: PASS scales={list(SCALES)} report={COMBINED_REPORT_PATH}")
    return 0


def _synthetic_items(item_count: int) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for index in range(item_count):
        embedding = [0.0] * VECTOR_DIMENSIONS
        embedding[index % VECTOR_DIMENSIONS] = 1.0
        items.append(
            {
                "item_id": f"item-{index:06}",
                "content_hash": None,
                "embedding": embedding,
                "valid_from_micros": 0,
                "valid_to_micros": 1_000_000,
                "blocking_keys": [f"block-{index // BLOCK_SIZE}"],
                "graph_neighbors": [],
                "lineage_ancestors": [],
            }
        )
    return items


def _native_module() -> NativeModule:
    library = _native_library_path()
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix, str) or not suffix:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    temporary = tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-perf-")
    temp_root = Path(temporary.name)
    destination = temp_root / f"{MODULE_NAME}{suffix}"
    shutil.copy2(library, destination)
    specification = importlib.util.spec_from_file_location(MODULE_NAME, destination)
    if specification is None or specification.loader is None:
        temporary.cleanup()
        raise RuntimeError(f"unable to load native extension from {destination}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    # Keep the temporary directory alive for the loaded extension lifetime.
    setattr(module, "_heterarchy_perf_tempdir", temporary)
    return cast(NativeModule, module)


def _native_library_path() -> Path:
    configured = os.environ.get("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    if not configured:
        raise RuntimeError("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY is required")
    path = Path(configured).resolve()
    if not path.is_file():
        raise RuntimeError(f"native extension artifact is missing: {path}")
    return path


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(value)
    return int(value) * 1024


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_object(value: bytes) -> dict[str, object]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise TypeError("expected JSON object")
    return cast(dict[str, object], decoded)


if __name__ == "__main__":
    raise SystemExit(main())
