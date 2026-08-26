"""Real PyO3 parity for bounded graph candidate selection over an active projection."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sysconfig
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_NAME = "heterarchy_alexandria_native"


class NativeModule(Protocol):
    """Narrow native surface exercised by this candidate-selection parity gate."""

    def compute_contract_version(self) -> int: ...

    def select_graph_projection_candidates_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-graph-selector-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        response = _load_json_bytes(
            module.select_graph_projection_candidates_json(
                json.dumps(_request_payload(), separators=(",", ":")).encode()
            )
        )
        if response.get("contract_version") != 1:
            raise AssertionError("graph selector contract version mismatch")
        if response.get("graph_compute_version") != 1:
            raise AssertionError("graph selector compute version mismatch")
        traversals = response.get("traversals")
        if not isinstance(traversals, list) or len(traversals) != 1:
            raise AssertionError("graph selector traversal count mismatch")
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise AssertionError("graph selector candidate count mismatch")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise AssertionError("graph selector candidate must be an object")
        if candidate.get("note_id") != "target":
            raise AssertionError(f"unexpected selected candidate: {candidate!r}")
        if candidate.get("min_depth") != 2:
            raise AssertionError("selected graph candidate depth mismatch")
        shared = candidate.get("shared_title_trigrams")
        union = candidate.get("title_trigram_union")
        if not isinstance(shared, int) or shared < 3:
            raise AssertionError("selected graph candidate shared trigram evidence mismatch")
        if not isinstance(union, int) or union < shared:
            raise AssertionError("selected graph candidate trigram union mismatch")
        path_hops = candidate.get("path_hops")
        if not isinstance(path_hops, list) or len(path_hops) != 2:
            raise AssertionError(f"selected graph candidate path mismatch: {path_hops!r}")
        expected_hops = [
            {
                "edge_id": "e1",
                "source_note_id": "seed",
                "target_note_id": "middle",
                "relation": "wikilink",
                "direction": "outgoing",
                "depth": 1,
            },
            {
                "edge_id": "e2",
                "source_note_id": "middle",
                "target_note_id": "target",
                "relation": "wikilink",
                "direction": "outgoing",
                "depth": 2,
            },
        ]
        if path_hops != expected_hops:
            raise AssertionError(f"selected graph candidate path evidence mismatch: {path_hops!r}")
    print("graph-candidate-selection-ffi-parity: PASS cases=1 call_count=1")
    return 0


def _request_payload() -> dict[str, object]:
    return {
        "contract_version": 1,
        "graph_compute_version": 1,
        "projection": {
            "nodes": [
                _node("seed", "Migration Plan"),
                _node("middle", "Migration Working Notes"),
                _node("target", "Runtime Seal Verification"),
                _node("noise", "Unrelated Archive"),
            ],
            "edges": [
                _edge("e1", "seed", "middle"),
                _edge("e2", "middle", "target"),
                _edge("e3", "seed", "noise"),
            ],
        },
        "traversal_requests": [
            {
                "request_id": "selection",
                "start_note_id": "seed",
                "direction": "outgoing",
                "relations": ["wikilink"],
                "max_depth": 2,
                "max_results": 50,
            }
        ],
        "primary_note_ids": ["seed"],
        "query": "runtime seal verification status",
        "max_candidates": 1,
        "min_shared_trigrams": 3,
    }


def _node(note_id: str, title: str) -> dict[str, object]:
    return {
        "note_id": note_id,
        "relative_path": f"Contexts/{note_id}.md",
        "alexandria_type": "context",
        "title": title,
        "status": "active",
        "project": "heterarchy-alexandria",
    }


def _edge(edge_id: str, source: str, target: str) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "source_note_id": source,
        "source_path": f"Contexts/{source}.md",
        "target_note_id": target,
        "target_path": f"Contexts/{target}.md",
        "relation": "wikilink",
        "confidence": 1.0,
        "source_kind": "wikilink",
    }


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


def _load_json_bytes(payload: bytes) -> dict[str, object]:
    value = json.loads(payload)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("expected a JSON object with string keys")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
