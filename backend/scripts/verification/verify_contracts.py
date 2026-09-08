"""Run repository Python contract checks without local agent configuration."""

from __future__ import annotations

import subprocess
import sys

from _verification_common import (
    REPOSITORY_ROOT,
    VERIFICATION_ROOT,
    profile_enabled,
    rule_enabled,
    source_roots,
)

BASELINE = (
    "verify_type_contracts.py",
    "verify_dynamic_attribute_contracts.py",
)
OPTIONAL = (
    ("rule", "async", "verify_async_contracts.py"),
    ("rule", "pydantic", "verify_schema_contracts.py"),
    ("profile", "fastapi", "verify_fastapi_contracts.py"),
    ("profile", "dependency_injector", "verify_dependency_injector_contracts.py"),
)


def main() -> int:
    source_roots()
    verifiers = list(BASELINE)
    for family, name, verifier in OPTIONAL:
        enabled = rule_enabled(name) if family == "rule" else profile_enabled(name)
        if enabled:
            verifiers.append(verifier)
    for verifier in verifiers:
        path = VERIFICATION_ROOT / verifier
        if not path.is_file():
            print(f"mechanical-contracts: missing enabled verifier: {verifier}")
            return 1
        result = subprocess.run(
            (sys.executable, str(path)), cwd=REPOSITORY_ROOT, check=False
        )
        if result.returncode != 0:
            print(f"mechanical-contracts: FAIL: {verifier} exited {result.returncode}")
            return result.returncode
    print(f"mechanical-contracts: PASS ({len(verifiers)} enabled verifiers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
