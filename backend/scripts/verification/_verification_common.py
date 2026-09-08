"""Shared helpers for fail-closed Python mechanical contract verifiers."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

VERIFICATION_ROOT: Final = Path(__file__).resolve().parent
REPOSITORY_ROOT: Final = VERIFICATION_ROOT.parents[2]
CONTRACT_CONFIG_PATH: Final = VERIFICATION_ROOT / "contracts.toml"


def load_contract_config() -> dict[str, object]:
    if not CONTRACT_CONFIG_PATH.is_file():
        raise RuntimeError(f"missing required contract config: {CONTRACT_CONFIG_PATH}")
    return tomllib.loads(CONTRACT_CONFIG_PATH.read_text(encoding="utf-8"))


def source_roots() -> tuple[Path, ...]:
    config = load_contract_config()
    project = config.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("contracts.toml is missing [project]")
    raw_roots = project.get("source_roots")
    if (
        not isinstance(raw_roots, list)
        or not raw_roots
        or not all(isinstance(item, str) for item in raw_roots)
    ):
        raise RuntimeError(
            "contracts.toml project.source_roots must be a non-empty string list"
        )
    roots = tuple(REPOSITORY_ROOT / item for item in raw_roots)
    missing = tuple(path for path in roots if not path.is_dir())
    if missing:
        raise RuntimeError(f"configured source roots do not exist: {missing}")
    return roots


def rule_enabled(name: str) -> bool:
    section = load_contract_config().get("rules")
    if not isinstance(section, dict):
        raise RuntimeError("contracts.toml is missing [rules]")
    value = section.get(name)
    if not isinstance(value, bool):
        raise RuntimeError(f"contracts.toml rules.{name} must be boolean")
    return value


def profile_enabled(name: str) -> bool:
    section = load_contract_config().get("profiles")
    if not isinstance(section, dict):
        raise RuntimeError("contracts.toml is missing [profiles]")
    value = section.get(name)
    if not isinstance(value, bool):
        raise RuntimeError(f"contracts.toml profiles.{name} must be boolean")
    return value


def production_python_files() -> Iterator[Path]:
    files: list[Path] = []
    for root in source_roots():
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and ".agents" not in path.parts
        )
    yield from sorted(set(files))


def parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def adjacent_marker(node: ast.AST, lines: list[str], marker: str) -> bool:
    line = max(getattr(node, "lineno", 1) - 1, 0)
    return any(
        marker in text for text in lines[max(line - 1, 0) : min(line + 1, len(lines))]
    )


def annotation_contains_bare_collection(annotation: ast.expr) -> bool:
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


def attribute_path(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = attribute_path(node.value)
        return (*parent, node.attr) if parent is not None else None
    return None


def base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Subscript):
        return base_name(node.value)
    path = attribute_path(node)
    return path[-1] if path else ""


def fail_or_pass(label: str, violations: Iterable[str]) -> int:
    rows = sorted(set(violations))
    if not rows:
        print(f"{label}: PASS")
        return 0
    print(f"{label}: FAIL ({len(rows)} violations)")
    for row in rows:
        print(f"- {row}")
    return 1
