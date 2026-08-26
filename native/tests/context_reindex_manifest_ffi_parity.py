"""Real PyO3 parity for deterministic Context reindex-manifest validation."""

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
CORPUS_PATH = REPOSITORY_ROOT / "native/golden/context_reindex_manifest.v1.json"
MODULE_NAME = "heterarchy_alexandria_native"
_IDENTITY_FIELDS = (
    "scope",
    "project",
    "workspace_id",
    "agent_id",
    "user_id",
    "session_id",
    "content_hash",
)
_RELATION_FIELDS = ("supersedes_context_id", "superseded_by_context_id")


class NativeModule(Protocol):
    def compute_contract_version(self) -> int: ...
    def compute_context_reindex_manifest_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_object(CORPUS_PATH.read_bytes())
    if corpus.get("contract_version") != 1 or corpus.get("manifest_version") != 1:
        raise AssertionError("Context reindex manifest corpus version mismatch")
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        raise TypeError("corpus cases must be a list")

    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        native = _load_native_module(Path(directory))
        if native.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        for raw_case in cases:
            if not isinstance(raw_case, dict):
                raise TypeError("manifest corpus case must be an object")
            raw_candidates = raw_case.get("candidates")
            if not isinstance(raw_candidates, list):
                raise TypeError("manifest corpus candidates must be a list")
            payload = {
                "contract_version": 1,
                "manifest_version": 1,
                "candidates": [_normalized_candidate(raw) for raw in raw_candidates],
            }
            actual = _load_object(
                native.compute_context_reindex_manifest_json(_encode(payload))
            )
            if actual != raw_case.get("expected"):
                raise AssertionError(
                    f"{raw_case.get('name')}: real-extension manifest parity mismatch"
                )
    print(f"context-reindex-manifest-ffi-parity: PASS cases={len(cases)}")
    return 0


def _normalized_candidate(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("manifest corpus candidate must be an object")
    note_id = _required_text(value, "note_id")
    relative_path = _required_text(value, "relative_path")
    canonical_relative_path = _required_text(value, "canonical_relative_path")
    alexandria_type = _required_text(value, "alexandria_type")
    candidate: dict[str, object] = {
        "note_id": note_id,
        "relative_path": relative_path,
        "canonical_relative_path": canonical_relative_path,
        "is_context": alexandria_type == "context",
    }
    for field_name in _IDENTITY_FIELDS:
        raw = value.get(field_name)
        candidate[field_name] = raw if isinstance(raw, str) else None
    for field_name in _RELATION_FIELDS:
        raw = value.get(field_name)
        candidate[field_name] = raw if isinstance(raw, str) else None
    return candidate


def _required_text(value: dict[object, object], field_name: str) -> str:
    raw = value.get(field_name)
    if not isinstance(raw, str):
        raise TypeError(f"manifest candidate {field_name} must be a string")
    return raw


def _load_native_module(temp_root: Path) -> NativeModule:
    library = _native_library_path()
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix, str) or not suffix:
        raise RuntimeError("Python EXT_SUFFIX is unavailable")
    destination = temp_root / f"{MODULE_NAME}{suffix}"
    shutil.copy2(library, destination)
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


def _native_library_path() -> Path:
    configured = os.environ.get("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY")
    if not configured:
        raise RuntimeError("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY is required")
    path = Path(configured).resolve()
    if not path.is_file():
        raise RuntimeError(f"native extension artifact is missing: {path}")
    return path


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_object(value: bytes) -> dict[str, object]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise TypeError("expected JSON object")
    return cast(dict[str, object], decoded)


if __name__ == "__main__":
    raise SystemExit(main())
