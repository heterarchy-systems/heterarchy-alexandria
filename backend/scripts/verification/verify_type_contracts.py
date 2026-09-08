"""Verify baseline public production type contracts."""

from __future__ import annotations

import ast

from _verification_common import (
    adjacent_marker,
    annotation_contains_bare_collection,
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
    source_lines,
)

ALLOW_ANY = "type-contract: allow-any"


def arguments(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.arg, ...]:
    rows = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg is not None:
        rows.append(node.args.vararg)
    if node.args.kwarg is not None:
        rows.append(node.args.kwarg)
    return tuple(rows)


def public_callables(
    tree: ast.Module,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    rows: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and not node.name.startswith("_"):
            rows.append(node)
        elif isinstance(node, ast.ClassDef):
            rows.extend(
                member
                for member in node.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not member.name.startswith("_")
            )
    return tuple(rows)


def main() -> int:
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        lines = source_lines(path)
        for node in public_callables(tree):
            if node.returns is None:
                violations.append(
                    f"{relative(path)}:{node.lineno}: public callable {node.name!r} has no return annotation"
                )
            elif annotation_contains_bare_collection(node.returns):
                violations.append(
                    f"{relative(path)}:{node.lineno}: public callable {node.name!r} return annotation contains a bare collection"
                )
            for arg in arguments(node):
                if arg.arg in {"self", "cls"}:
                    continue
                if arg.annotation is None:
                    violations.append(
                        f"{relative(path)}:{node.lineno}: public callable {node.name!r} parameter {arg.arg!r} has no annotation"
                    )
                elif annotation_contains_bare_collection(arg.annotation):
                    violations.append(
                        f"{relative(path)}:{arg.lineno}: public callable {node.name!r} parameter {arg.arg!r} contains a bare collection annotation"
                    )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and node.id == "Any"
                and not adjacent_marker(node, lines, ALLOW_ANY)
            ):
                violations.append(  # noqa: PERF401
                    f"{relative(path)}:{node.lineno}: Any requires a narrow dynamic-boundary justification ({ALLOW_ANY})"
                )
    return fail_or_pass("type-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
