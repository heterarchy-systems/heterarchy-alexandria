"""Real PyO3 parity for bounded traversal over an already-built graph projection."""

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
    """Narrow native surface exercised by this parity gate."""

    def compute_contract_version(self) -> int: ...

    def traverse_graph_projection_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-graph-traversal-") as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        payload = _request_payload()
        response = _load_json_bytes(
            module.traverse_graph_projection_json(
                json.dumps(payload, separators=(",", ":")).encode()
            )
        )
        if response.get("contract_version") != 1:
            raise AssertionError("graph traversal contract version mismatch")
        if response.get("graph_compute_version") != 1:
            raise AssertionError("graph traversal compute version mismatch")
        traversals = response.get("traversals")
        if not isinstance(traversals, list) or len(traversals) != 3:
            raise AssertionError("graph traversal result count mismatch")
        _assert_visits(traversals[0], [("a", 0), ("b", 1)], truncated=True)
        _assert_visits(traversals[1], [("a", 0), ("b", 1), ("c", 2)], truncated=False)
        _assert_visits(traversals[2], [("a", 0), ("b", 1), ("c", 2)], truncated=False)
    print("graph-traversal-ffi-parity: PASS cases=3 call_count=1")
    return 0


def _request_payload() -> dict[str, object]:
    return {
        "contract_version": 1,
        "graph_compute_version": 1,
        "projection": {
            "nodes": [
                _node("a"),
                _node("b"),
                _node("c"),
            ],
            "edges": [
                _edge("e1", "a", "b", "wikilink", "wikilink"),
                _edge("e2", "b", "c", "wikilink", "wikilink"),
                _edge("e3", "c", "a", "related", "frontmatter"),
            ],
        },
        "traversal_requests": [
            _traversal("depth-one", 1, ["wikilink"]),
            _traversal("depth-two", 2, ["wikilink"]),
            _traversal("cycle-safe", 8, []),
        ],
    }


def _node(note_id: str) -> dict[str, object]:
    return {
        "note_id": note_id,
        "relative_path": f"Contexts/{note_id}.md",
        "alexandria_type": "context",
        "title": note_id.upper(),
        "status": "active",
        "project": None,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    relation: str,
    source_kind: str,
) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "source_note_id": source,
        "source_path": f"Contexts/{source}.md",
        "target_note_id": target,
        "target_path": f"Contexts/{target}.md",
        "relation": relation,
        "confidence": 1.0,
        "source_kind": source_kind,
    }


def _traversal(
    request_id: str,
    max_depth: int,
    relations: list[str],
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "start_note_id": "a",
        "direction": "outgoing",
        "relations": relations,
        "max_depth": max_depth,
        "max_results": 10,
    }


def _assert_visits(value: object, expected: list[tuple[str, int]], truncated: bool) -> None:
    if not isinstance(value, dict):
        raise AssertionError("graph traversal item must be an object")
    visits = value.get("visits")
    if not isinstance(visits, list):
        raise AssertionError("graph traversal visits must be a list")
    actual = []
    for visit in visits:
        if not isinstance(visit, dict):
            raise AssertionError("graph traversal visit must be an object")
        note_id = visit.get("note_id")
        depth = visit.get("depth")
        if not isinstance(note_id, str) or not isinstance(depth, int):
            raise AssertionError("graph traversal visit shape mismatch")
        actual.append((note_id, depth))
    if actual != expected:
        raise AssertionError(f"graph traversal visits mismatch: {actual!r}")
    if value.get("truncated") is not truncated:
        raise AssertionError("graph traversal truncation mismatch")


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
