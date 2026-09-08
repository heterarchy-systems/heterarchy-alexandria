"""Verify mechanically reliable FastAPI profile contracts."""

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

DEPRECATED_RESPONSES = {"ORJSONResponse", "UJSONResponse"}


def decorator_call_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    path = attribute_path(target)
    return path[-1] if path else ""


def main() -> int:
    if not profile_enabled("fastapi"):
        print("fastapi-contracts: NOT APPLICABLE")
        return 0
    violations: list[str] = []
    for path in production_python_files():
        for node in ast.walk(parse_python(path)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "fastapi.responses"
            ):
                for name in sorted(
                    {alias.name for alias in node.names} & DEPRECATED_RESPONSES
                ):
                    violations.append(  # noqa: PERF401
                        f"{relative(path)}:{node.lineno}: deprecated FastAPI {name}"
                    )
            elif (
                isinstance(node, ast.Call)
                and base_name(node.func) in DEPRECATED_RESPONSES
            ):
                violations.append(
                    f"{relative(path)}:{node.lineno}: deprecated FastAPI response class {base_name(node.func)}"
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and decorator_call_name(decorator) == "on_event"
                        and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                        and decorator.args[0].value in {"startup", "shutdown"}
                    ):
                        violations.append(  # noqa: PERF401
                            f"{relative(path)}:{node.lineno}: deprecated FastAPI on_event lifecycle; use lifespan"
                        )
    return fail_or_pass("fastapi-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
