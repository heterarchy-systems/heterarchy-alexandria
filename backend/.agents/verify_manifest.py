#!/usr/bin/env python3
"""Verify the Alexandria rule and skill manifest without third-party packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypedDict, cast

AGENTS_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = AGENTS_ROOT / "MANIFEST.json"


class ManifestEntry(TypedDict):
    """One manifest-owned file digest."""

    path: str
    bytes: int
    sha256: str


class ManifestPayload(TypedDict):
    """Typed manifest structure consumed by the verifier."""

    name: str
    schema_version: int
    source_roots: list[str]
    files: list[ManifestEntry]


def _load_manifest() -> ManifestPayload:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("MANIFEST.json must contain an object")
    return cast(ManifestPayload, payload)


def main() -> int:
    """Fail when a live rule/skill file differs from the generated manifest."""
    if not MANIFEST_PATH.is_file():
        print("MANIFEST.json is missing; run .agents/generate_manifest.py")
        return 1
    manifest = _load_manifest()
    expected_paths = {entry["path"] for entry in manifest["files"]}
    actual_paths = {
        path.relative_to(AGENTS_ROOT).as_posix()
        for relative_root in manifest["source_roots"]
        for path in (AGENTS_ROOT / relative_root).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    errors: list[str] = []
    if expected_paths != actual_paths:
        errors.append(
            f"file set mismatch: missing={sorted(expected_paths - actual_paths)}, "
            f"unexpected={sorted(actual_paths - expected_paths)}"
        )
    for entry in manifest["files"]:
        path = AGENTS_ROOT / entry["path"]
        if not path.is_file():
            continue
        content = path.read_bytes()
        if len(content) != entry["bytes"]:
            errors.append(f"byte count mismatch: {entry['path']}")
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            errors.append(f"sha256 mismatch: {entry['path']}")
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"manifest-contracts: PASS ({len(expected_paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
