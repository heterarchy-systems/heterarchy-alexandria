"""Verify feature-owned StrEnum placement and legacy enum bases."""

from __future__ import annotations

import ast
from pathlib import Path

from _verification_common import (
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
    source_lines,
)

_LOCAL_ENUM_MARKER = "enum-contract: local"


def _base_terminal_name(base: ast.expr) -> str:
    """Return the terminal name of one class base expression."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _has_local_marker(path: Path, node: ast.ClassDef) -> bool:
    """Return whether one unavoidable local enum has a narrow reason marker."""
    lines = source_lines(path)
    start = max(node.lineno - 2, 0)
    stop = min(node.lineno, len(lines))
    return any(_LOCAL_ENUM_MARKER in line for line in lines[start:stop])


def _is_feature_owned_enum_module(path: Path) -> bool:
    """Return whether a module name communicates explicit enum ownership."""
    return path.name.endswith("_enums.py")


def main() -> int:
    """Run the fail-closed Alexandria enum contract verifier."""
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {_base_terminal_name(base) for base in node.bases}
            if "Enum" in base_names and "str" in base_names:
                violations.append(
                    f"{relative(path)}:{node.lineno}: {node.name} uses 'str, Enum'; use StrEnum"
                )
            if "StrEnum" not in base_names:
                continue
            if _is_feature_owned_enum_module(path) or _has_local_marker(path, node):
                continue
            violations.append(
                f"{relative(path)}:{node.lineno}: StrEnum {node.name} must move to a feature-owned '*_enums.py' module; use '{_LOCAL_ENUM_MARKER} <reason>' only for an unavoidable protocol-local enum"
            )
    return fail_or_pass("enum-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
