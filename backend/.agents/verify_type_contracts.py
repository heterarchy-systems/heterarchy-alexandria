"""Verify Alexandria production typing contracts without a debt baseline."""

from __future__ import annotations

import ast

from _verification_common import (
    annotation_contains_bare_collection,
    fail_or_pass,
    node_text_has_marker,
    parse_python,
    production_python_files,
    relative,
    source_lines,
)

_ALLOW_ANY = "type-contract: allow-any"
_ALLOW_KEYWORD_ONLY = "type-contract: allow-keyword-only"


def _any_is_allowed(node: ast.Name, lines: list[str]) -> bool:
    start = max(node.lineno - 2, 0)
    stop = min(node.lineno + 1, len(lines))
    return any(_ALLOW_ANY in line for line in lines[start:stop])


def main() -> int:
    """Run the fail-closed production type contract verifier."""
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        lines = source_lines(path)
        rel = relative(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.returns is None:
                    violations.append(
                        f"{rel}:{node.lineno}: missing return annotation on {node.name}"
                    )
                arguments = [
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ]
                for argument in arguments:
                    if argument.arg in {"self", "cls"}:
                        continue
                    if argument.annotation is None:
                        violations.append(
                            f"{rel}:{argument.lineno}: missing parameter annotation for {node.name}.{argument.arg}"
                        )
                    elif annotation_contains_bare_collection(argument.annotation):
                        violations.append(
                            f"{rel}:{argument.lineno}: bare collection annotation for {node.name}.{argument.arg}"
                        )
                violations.extend(
                    f"{rel}:{argument.lineno}: missing variadic annotation for {node.name}.{argument.arg}"
                    for argument in (node.args.vararg, node.args.kwarg)
                    if argument is not None and argument.annotation is None
                )
                if node.returns is not None and annotation_contains_bare_collection(
                    node.returns
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: bare collection return annotation on {node.name}"
                    )
                if (
                    node.args.kwonlyargs
                    and node.args.vararg is None
                    and not node_text_has_marker(node, lines, _ALLOW_KEYWORD_ONLY)
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: bare keyword-only separator on {node.name}"
                    )
            if isinstance(node, ast.AnnAssign) and annotation_contains_bare_collection(
                node.annotation
            ):
                violations.append(
                    f"{rel}:{node.lineno}: bare collection field annotation"
                )
            if (
                isinstance(node, ast.Name)
                and node.id == "Any"
                and not _any_is_allowed(node, lines)
            ):
                violations.append(f"{rel}:{node.lineno}: unapproved Any")
    return fail_or_pass("type-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
