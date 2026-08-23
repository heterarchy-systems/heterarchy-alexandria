"""Real PyO3 parity for bounded reconciliation candidate discovery."""

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
CORPUS_PATH = REPOSITORY_ROOT / "native/corpora/reconciliation_candidates/v1/cases.json"
MODULE_NAME = "heterarchy_alexandria_native"


class NativeModule(Protocol):
    def compute_contract_version(self) -> int: ...
    def compute_reconciliation_candidates_json(self, payload: bytes) -> bytes: ...


def main() -> int:
    corpus = _load_object(CORPUS_PATH.read_bytes())
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        raise TypeError("corpus cases must be a list")
    with tempfile.TemporaryDirectory(prefix="heterarchy-alexandria-native-") as directory:
        native = _load_native_module(Path(directory))
        if native.compute_contract_version() != 1:
            raise AssertionError("native compute contract version must be 1")
        for raw_case in cases:
            if not isinstance(raw_case, dict):
                raise TypeError("candidate corpus case must be an object")
            payload = {
                "contract_version": 1,
                "candidate_version": 1,
                "policy": raw_case["policy"],
                "items": raw_case["items"],
            }
            actual = _load_object(
                native.compute_reconciliation_candidates_json(_encode(payload))
            )
            if actual != raw_case["expected"]:
                raise AssertionError(f"{raw_case.get('name')}: real-extension candidate parity mismatch")
    print(f"reconciliation-candidate-ffi-parity: PASS cases={len(cases)} call_count={len(cases)}")
    return 0


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
