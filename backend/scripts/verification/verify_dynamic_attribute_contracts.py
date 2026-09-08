"""Reject dynamic attribute built-ins in production Python source."""

from __future__ import annotations

import ast

from _verification_common import (
    attribute_path,
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
)

FORBIDDEN_NAMES = frozenset({"getattr", "hasattr", "setattr"})


def main() -> int:
    violations: list[str] = []
    for path in production_python_files():
        for node in ast.walk(parse_python(path)):
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                violations.append(
                    f"{relative(path)}:{node.lineno}: name {node.id!r} is forbidden in production Python"
                )
            elif isinstance(node, ast.Attribute):
                target = attribute_path(node)
                if target in {
                    ("builtins", "getattr"),
                    ("builtins", "hasattr"),
                    ("builtins", "setattr"),
                }:
                    violations.append(
                        f"{relative(path)}:{node.lineno}: dynamic attribute builtin {'.'.join(target)} is forbidden"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module == "builtins":
                violations.extend(
                    f"{relative(path)}:{node.lineno}: importing builtins.{alias.name} is forbidden"
                    for alias in node.names
                    if alias.name in FORBIDDEN_NAMES
                )
    return fail_or_pass("dynamic-attribute-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
