"""Verify Alexandria async/blocking-boundary contracts."""

from __future__ import annotations

import ast

from _verification_common import (
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
)


def main() -> int:
    """Reject direct production asyncio.to_thread usage."""
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        rel = relative(path)
        imported_to_thread = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "asyncio"
                and any(alias.name == "to_thread" for alias in node.names)
            ):
                imported_to_thread = True
                violations.append(
                    f"{rel}:{node.lineno}: direct asyncio.to_thread import forbidden"
                )
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "asyncio"
                and node.attr == "to_thread"
            ):
                violations.append(
                    f"{rel}:{node.lineno}: direct asyncio.to_thread usage forbidden"
                )
            if (
                imported_to_thread
                and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "to_thread"
            ):
                violations.append(
                    f"{rel}:{node.lineno}: direct to_thread() usage forbidden"
                )
    return fail_or_pass("async-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
