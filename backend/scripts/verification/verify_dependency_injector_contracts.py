"""Verify mechanically detectable Dependency Injector contracts."""

from __future__ import annotations

import ast

from _verification_common import (
    attribute_path,
    base_name,
    fail_or_pass,
    parse_python,
    production_python_files,
    profile_enabled,
    relative,
)


def decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    path = attribute_path(target)
    return path[-1] if path else ""


def main() -> int:
    if not profile_enabled("dependency_injector"):
        print("dependency-injector-contracts: NOT APPLICABLE")
        return 0
    violations: list[str] = []
    for path in production_python_files():
        for node in ast.walk(parse_python(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [decorator_name(item) for item in node.decorator_list]
                if "inject" in names and names[-1] != "inject":
                    violations.append(
                        f"{relative(path)}:{node.lineno}: @inject must be the innermost/first-applied decorator"
                    )
            elif isinstance(node, ast.Call):
                call = attribute_path(node.func)
                if call and call[-2:] == ("providers", "Singleton") and node.args:
                    dependency = base_name(node.args[0])
                    if dependency in {"Session", "AsyncSession"} or dependency.endswith(
                        "Session"
                    ):
                        violations.append(
                            f"{relative(path)}:{node.lineno}: session-like object configured as DI Singleton"
                        )
    return fail_or_pass("dependency-injector-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
