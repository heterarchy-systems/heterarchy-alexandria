"""Verify baseline Pydantic v2 contract compatibility."""

from __future__ import annotations

import ast

from _verification_common import (
    base_name,
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
    rule_enabled,
)


def main() -> int:
    if not rule_enabled("pydantic"):
        print("schema-contracts: NOT APPLICABLE")
        return 0
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = {alias.name for alias in node.names}
                if module.startswith("pydantic.v1"):
                    violations.append(
                        f"{relative(path)}:{node.lineno}: pydantic.v1 compatibility import in production code"
                    )
                if module == "pydantic" and {"validator", "root_validator"} & names:
                    violations.append(
                        f"{relative(path)}:{node.lineno}: v1 validator/root_validator API; use v2 validators"
                    )
            elif isinstance(node, ast.ClassDef):
                bases = {base_name(base) for base in node.bases}
                if bases & {"BaseModel", "RootModel"} and any(
                    isinstance(stmt, ast.ClassDef) and stmt.name == "Config"
                    for stmt in node.body
                ):
                    violations.append(
                        f"{relative(path)}:{node.lineno}: {node.name} uses legacy inner Config; use model_config/ConfigDict"
                    )
            elif isinstance(node, ast.Call) and base_name(node.func) == "parse_obj_as":
                violations.append(
                    f"{relative(path)}:{node.lineno}: parse_obj_as is legacy; use TypeAdapter"
                )
    return fail_or_pass("schema-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
