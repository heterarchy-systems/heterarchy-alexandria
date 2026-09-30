"""Real PyO3 parity for Rust-owned graph debt and suggestion diagnostics."""

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

    def compute_graph_diagnostics_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="heterarchy-alexandria-graph-diagnostics-"
    ) as directory:
        module = _load_native_module(Path(directory))
        if module.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        response = _load_json_bytes(
            module.compute_graph_diagnostics_json(
                json.dumps(_request_payload(), separators=(",", ":")).encode()
            )
        )
    if response.get("contract_version") != 1:
        raise AssertionError("diagnostics contract version mismatch")
    if response.get("graph_compute_version") != 1:
        raise AssertionError("diagnostics graph version mismatch")
    if response.get("total_orphans") != 3:
        raise AssertionError(f"unexpected orphan total: {response!r}")
    orphans = response.get("orphans")
    if not isinstance(orphans, list) or len(orphans) != 2:
        raise AssertionError(f"unexpected bounded orphan page: {orphans!r}")
    if orphans[0].get("relative_path") != "Contexts/aa-linked.md":
        raise AssertionError("stable orphan path ordering mismatch")
    if orphans[0].get("has_wikilink_connectivity") is not True:
        raise AssertionError("wikilink-only connectivity evidence missing")
    if response.get("next_cursor") != "Contexts/zz-candidate.md":
        raise AssertionError("orphan cursor mismatch")
    suggestions = response.get("suggestions")
    if not isinstance(suggestions, list) or not suggestions:
        raise AssertionError("relation suggestion evidence missing")
    if suggestions[0].get("candidate_note_id") != "candidate":
        raise AssertionError("suggestion candidate mismatch")
    print("graph-diagnostics-ffi-parity: PASS cases=1 call_count=1")
    return 0


def _request_payload() -> dict[str, object]:
    return {
        "contract_version": 1,
        "graph_compute_version": 1,
        "notes": [
            _note("seed", "Contexts/seed.md", "Seed", ["topic"]),
            _note("linked", "Contexts/aa-linked.md", "Linked", []),
            _note("candidate", "Contexts/zz-candidate.md", "Candidate", ["topic"]),
            _note("orphan", "Contexts/zz-orphan.md", "Orphan", []),
            _note("owner", "Contexts/owner.md", "Owner", [], project="other"),
        ],
        "edges": [
            _edge("e0", "owner", "seed", "contains", "frontmatter"),
            _edge("e1", "seed", "linked", "wikilink", "wikilink"),
            _edge("e2", "seed", "candidate", "related", "frontmatter"),
        ],
        "orphan_census": {"project": "p", "cursor": None, "limit": 2},
        "relation_suggestions": {"seed_note_id": "seed", "limit": 1},
    }


def _note(
    note_id: str,
    path: str,
    title: str,
    tags: list[str],
    project: str = "p",
) -> dict[str, object]:
    return {
        "note_id": note_id,
        "relative_path": path,
        "title": title,
        "project": project,
        "tags": tags,
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
        "target_note_id": target,
        "relation": relation,
        "source_kind": source_kind,
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
    if Path(str(module.__file__)).resolve() != destination.resolve():
        raise RuntimeError("native provenance mismatch")
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
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
