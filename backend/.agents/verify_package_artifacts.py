#!/usr/bin/env python3
"""Verify the built Alexandria wheel contains production code only."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = BACKEND_ROOT / "app"
FORBIDDEN_PREFIXES = ("tests/", ".agents/")
FORBIDDEN_SEGMENTS = ("/__pycache__/",)


def _expected_python_files() -> set[str]:
    return {
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in PRODUCTION_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def main() -> int:
    """Build an offline wheel and verify its production package surface."""
    errors: list[str] = []
    with TemporaryDirectory(prefix="alexandria-package-check-") as temporary_root:
        result = subprocess.run(
            (
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                temporary_root,
                "--offline",
                "--no-build-logs",
            ),
            cwd=BACKEND_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode
        wheel = next(Path(temporary_root).glob("*.whl"), None)
        if wheel is None:
            print("package-artifacts: wheel was not produced")
            return 1
        with ZipFile(wheel) as archive:
            names = set(archive.namelist())
    expected = _expected_python_files()
    missing = sorted(expected - names)
    errors.extend(f"wheel is missing production module: {path}" for path in missing)
    errors.extend(
        f"wheel contains forbidden package prefix: {prefix}"
        for prefix in FORBIDDEN_PREFIXES
        if any(name.startswith(prefix) for name in names)
    )
    errors.extend(
        f"wheel contains forbidden package segment: {segment}"
        for segment in FORBIDDEN_SEGMENTS
        if any(segment in name for name in names)
    )
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"package-artifacts: PASS ({len(expected)} production modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
