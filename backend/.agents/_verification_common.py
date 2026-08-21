"""Shared helpers for fail-closed Alexandria mechanical contract verifiers."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROOT = BACKEND_ROOT / ".agents"
PRODUCTION_ROOT = BACKEND_ROOT / "app"
RULES_ROOT = AGENTS_ROOT / "docs" / "rule"


def production_python_files() -> Iterator[Path]:
    """Yield production Python files in stable path order."""
    yield from sorted(PRODUCTION_ROOT.rglob("*.py"))


def parse_python(path: Path) -> ast.Module:
    """Parse one Python source file."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def relative(path: Path) -> str:
    """Return a backend-relative POSIX path."""
    return path.relative_to(BACKEND_ROOT).as_posix()


def source_lines(path: Path) -> list[str]:
    """Return source lines without newline characters."""
    return path.read_text(encoding="utf-8").splitlines()


def node_text_has_marker(
    node: ast.AST,
    lines: list[str],
    marker: str,
) -> bool:
    """Return whether a marker appears on or immediately around a node signature."""
    start = max(getattr(node, "lineno", 1) - 2, 0)
    body = getattr(node, "body", None)
    first_body_line = (
        getattr(body[0], "lineno", getattr(node, "lineno", 1))
        if isinstance(body, list) and body
        else getattr(node, "end_lineno", getattr(node, "lineno", 1))
    )
    stop = min(first_body_line, len(lines))
    return any(marker in line for line in lines[start:stop])


def annotation_contains_bare_collection(annotation: ast.expr) -> bool:
    """Return whether an annotation contains an unparameterized collection type."""
    bare_names = {"list", "dict", "tuple", "set", "frozenset"}
    parameterized_nodes: set[int] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Subscript):
            parameterized_nodes.add(id(node.value))
    return any(
        isinstance(node, ast.Name)
        and node.id in bare_names
        and id(node) not in parameterized_nodes
        for node in ast.walk(annotation)
    )


def call_name(node: ast.Call) -> str:
    """Return a stable short name for a call target when statically available."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def base_name(node: ast.expr) -> str:
    """Return the terminal name for a class base expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return base_name(node.value)
    return ""


def fail_or_pass(label: str, violations: Iterable[str]) -> int:
    """Print deterministic verifier output and return a process exit code."""
    rows = sorted(set(violations))
    if not rows:
        print(f"{label}: PASS")
        return 0
    print(f"{label}: FAIL ({len(rows)} violations)")
    for row in rows:
        print(f"- {row}")
    return 1
