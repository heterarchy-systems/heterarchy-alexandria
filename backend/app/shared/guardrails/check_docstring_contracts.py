"""AST-based production function and method docstring contract guard."""

from __future__ import annotations

import ast
from pathlib import Path

from app.shared.guardrails._common import iter_guard_target_paths, parse_module


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    """Return parameters that require documentation.

    Args:
        node: Function or method definition being inspected.

    Returns:
        Parameter names excluding implicit instance and class receivers.
    """
    arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    names = [
        argument.arg for argument in arguments if argument.arg not in {"self", "cls"}
    ]
    if node.args.vararg is not None:
        names.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        names.append(node.args.kwarg.arg)
    return tuple(names)


def _returns_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether the callable exposes a non-None result.

    Args:
        node: Function or method definition being inspected.

    Returns:
        True when the return annotation represents a meaningful value.
    """
    annotation = node.returns
    if annotation is None:
        return True
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return False
    return not (isinstance(annotation, ast.Name) and annotation.id == "None")


def _documented_args(docstring: str) -> set[str]:
    """Return parameter names documented in the Google-style Args section.

    Args:
        docstring: Normalized callable docstring text.

    Returns:
        Parameter names declared before the next top-level docstring section.
    """
    lines = docstring.splitlines()
    try:
        start = next(
            index for index, line in enumerate(lines) if line.strip() == "Args:"
        )
    except StopIteration:
        return set()
    documented: set[str] = set()
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped and not line.startswith((" ", "\t")) and stripped.endswith(":"):
            break
        if ":" not in stripped:
            continue
        name = stripped.split(":", 1)[0].lstrip("*")
        if name.isidentifier():
            documented.add(name)
    return documented


def _yields_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether this callable directly yields values.

    Args:
        node: Function or method definition being inspected.

    Returns:
        True when a direct yield expression exists in this callable body.
    """
    stack: list[ast.AST] = list(node.body)
    while stack:
        candidate = stack.pop()
        if isinstance(candidate, ast.Yield | ast.YieldFrom):
            return True
        if isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(candidate))
    return False


def collect_failures(backend_root: Path | None = None) -> list[str]:
    """Collect missing or incomplete production callable docstrings.

    Args:
        backend_root: Explicit backend root for tests or alternate invocations.

    Returns:
        Human-readable docstring contract violations.
    """
    failures: list[str] = []
    for path in iter_guard_target_paths(Path(__file__), backend_root=backend_root):
        tree = parse_module(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            docstring = ast.get_docstring(node)
            if docstring is None:
                failures.append(f"{path}:{node.lineno}:{node.name}: missing docstring")
                continue
            parameter_names = _parameter_names(node)
            if parameter_names and "Args:" not in docstring:
                failures.append(
                    f"{path}:{node.lineno}:{node.name}: docstring missing Args"
                )
            elif parameter_names:
                undocumented = sorted(
                    set(parameter_names) - _documented_args(docstring)
                )
                if undocumented:
                    failures.append(
                        f"{path}:{node.lineno}:{node.name}: undocumented Args: {', '.join(undocumented)}"
                    )
            if _yields_value(node):
                if "Yields:" not in docstring:
                    failures.append(
                        f"{path}:{node.lineno}:{node.name}: generator docstring missing Yields"
                    )
                continue
            if _returns_value(node) and "Returns:" not in docstring:
                failures.append(
                    f"{path}:{node.lineno}:{node.name}: docstring missing Returns"
                )
    return failures


def main() -> int:
    """Run the callable docstring guard.

    Returns:
        Process exit status for the docstring contract.
    """
    failures = collect_failures()
    if failures:
        print("docstring contract check failed:")
        for failure in failures:
            print(failure)
        return 1
    print("docstring contract check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
