#!/usr/bin/env python3
"""Run the canonical Alexandria mechanical contract gate sequence."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent
VERIFIERS = (
    "verify_manifest.py",
    "verify_schema_contracts.py",
    "verify_type_contracts.py",
    "verify_enum_contracts.py",
    "verify_boundary_contracts.py",
    "verify_database_contracts.py",
    "verify_async_contracts.py",
    "verify_backend_contracts.py",
    "verify_architecture_contracts.py",
    "verify_mcp_v2_contracts.py",
    "verify_package_artifacts.py",
)


def main() -> int:
    """Run every production-green mechanical gate and stop on the first failure."""
    for verifier in VERIFIERS:
        print(f"mechanical: {verifier}", flush=True)
        result = subprocess.run(
            [sys.executable, str(AGENTS_ROOT / verifier)],
            cwd=AGENTS_ROOT.parent,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    print("mechanical-contracts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
