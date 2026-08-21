"""Verify FastAPI/DI/JSON production boundary contracts."""

from __future__ import annotations

import ast

from _verification_common import (
    call_name,
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
)

_HTTP_MUTATION_METHODS = {"post", "put", "patch", "delete"}
_FRAMEWORK_REQUEST_NAMES = {"Request", "Response", "BackgroundTasks", "WebSocket"}


def _route_methods(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    methods: set[str] = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in _HTTP_MUTATION_METHODS:
            methods.add(target.attr)
    return methods


def _annotation_names(annotation: ast.expr) -> set[str]:
    return {item.id for item in ast.walk(annotation) if isinstance(item, ast.Name)}


def _is_request_schema(annotation: ast.expr) -> bool:
    names = _annotation_names(annotation)
    return any(
        name.endswith("Request") and name not in _FRAMEWORK_REQUEST_NAMES
        for name in names
    )


def _is_strict_json_dependency(annotation: ast.expr) -> bool:
    text = ast.unparse(annotation)
    return "Annotated[" in text and "Depends(" in text


def _default_is_provide_dependency(default: ast.expr | None) -> bool:
    if not isinstance(default, ast.Call) or call_name(default) != "Depends":
        return False
    return any(
        isinstance(node, ast.Name) and node.id == "Provide"
        for argument in default.args
        for node in ast.walk(argument)
    )


def main() -> int:
    """Run the fail-closed FastAPI/DI/JSON verifier."""
    violations: list[str] = []
    for path in production_python_files():
        tree = parse_python(path)
        rel = relative(path)
        postponed_annotations = any(
            isinstance(statement, ast.ImportFrom)
            and statement.module == "__future__"
            and any(alias.name == "annotations" for alias in statement.names)
            for statement in tree.body
        )
        if postponed_annotations and any(
            isinstance(argument, ast.arg)
            and argument.annotation is not None
            and "Provide[" in ast.unparse(argument.annotation)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
        ):
            violations.append(
                f"{rel}: postponed annotations hide Annotated Provide markers from dependency-injector"
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "json" for alias in node.names
            ):
                violations.append(
                    f"{rel}:{node.lineno}: stdlib json import forbidden in production"
                )
            if isinstance(node, ast.ImportFrom):
                if node.module == "json":
                    violations.append(
                        f"{rel}:{node.lineno}: stdlib json import forbidden in production"
                    )
                if any(
                    alias.name in {"JSONResponse", "ORJSONResponse"}
                    for alias in node.names
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: JSONResponse/ORJSONResponse import forbidden"
                    )
            if isinstance(node, ast.Call) and call_name(node) in {
                "JSONResponse",
                "ORJSONResponse",
            }:
                violations.append(
                    f"{rel}:{node.lineno}: manual JSON response forbidden"
                )
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_methods = _route_methods(node)
            arguments = [*node.args.posonlyargs, *node.args.args]
            positional_defaults = [None] * (
                len(arguments) - len(node.args.defaults)
            ) + list(node.args.defaults)
            for argument, default in zip(arguments, positional_defaults, strict=True):
                if _default_is_provide_dependency(default):
                    violations.append(
                        f"{rel}:{argument.lineno}: DI parameter {node.name}.{argument.arg} must use Annotated Depends(Provide[...])"
                    )
                if (
                    route_methods
                    and argument.annotation is not None
                    and _is_request_schema(argument.annotation)
                    and not _is_strict_json_dependency(argument.annotation)
                ):
                    violations.append(
                        f"{rel}:{argument.lineno}: strict JSON request {node.name}.{argument.arg} must use shared model_validate_json dependency"
                    )
            for argument, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults, strict=True
            ):
                if _default_is_provide_dependency(default):
                    violations.append(
                        f"{rel}:{argument.lineno}: DI parameter {node.name}.{argument.arg} must use Annotated Depends(Provide[...])"
                    )
                if (
                    route_methods
                    and argument.annotation is not None
                    and _is_request_schema(argument.annotation)
                    and not _is_strict_json_dependency(argument.annotation)
                ):
                    violations.append(
                        f"{rel}:{argument.lineno}: strict JSON request {node.name}.{argument.arg} must use shared model_validate_json dependency"
                    )
    return fail_or_pass("backend-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
