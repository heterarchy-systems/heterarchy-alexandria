"""Verify mechanically detectable asyncio execution-boundary mistakes."""

from __future__ import annotations

import ast

from _verification_common import (
    attribute_path,
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
    rule_enabled,
)


def attach_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent


def main() -> int:
    if not rule_enabled("async"):
        print("async-contracts: NOT APPLICABLE")
        return 0
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        attach_parents(tree)
        for function in ast.walk(tree):
            if not isinstance(function, ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                call = attribute_path(node.func)
                if call == ("asyncio", "run"):
                    violations.append(
                        f"{relative(path)}:{node.lineno}: nested asyncio.run() inside async code"
                    )
                elif call and call[-1] == "run_until_complete":
                    violations.append(
                        f"{relative(path)}:{node.lineno}: run_until_complete() inside async code"
                    )
                elif call == ("time", "sleep"):
                    violations.append(
                        f"{relative(path)}:{node.lineno}: time.sleep() blocks the event loop"
                    )
                elif call in {
                    ("subprocess", "run"),
                    ("subprocess", "Popen"),
                    ("subprocess", "call"),
                    ("subprocess", "check_call"),
                    ("subprocess", "check_output"),
                }:
                    violations.append(
                        f"{relative(path)}:{node.lineno}: blocking subprocess API inside async code"
                    )
                elif call == ("asyncio", "create_task") and isinstance(
                    getattr(node, "_parent", None), ast.Expr
                ):
                    violations.append(
                        f"{relative(path)}:{node.lineno}: asyncio.create_task() result is discarded; task needs an owner"
                    )
    return fail_or_pass("async-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
