#!/usr/bin/env python3
"""Generate the deterministic Alexandria rule and skill manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = AGENTS_ROOT / "MANIFEST.json"
SOURCE_ROOTS = (
    Path("docs/rule"),
    Path("fastapi-skill"),
    Path("dependency-injector-skill"),
)


def _source_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for relative_root in SOURCE_ROOTS:
        root = AGENTS_ROOT / relative_root
        if not root.is_dir():
            raise FileNotFoundError(f"manifest source root is missing: {relative_root}")
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    return tuple(sorted(set(files)))


def _entry(path: Path) -> dict[str, str | int]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(AGENTS_ROOT).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def main() -> int:
    """Write a stable hash manifest for the live development contract sources."""
    payload = {
        "name": "heterarchy-alexandria-rule-harness",
        "schema_version": 1,
        "source_roots": [path.as_posix() for path in SOURCE_ROOTS],
        "files": [_entry(path) for path in _source_files()],
    }
    MANIFEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(payload['files'])} manifest entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
