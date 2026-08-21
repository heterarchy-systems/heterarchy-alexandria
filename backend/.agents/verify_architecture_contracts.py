"""Verify Alexandria module, package, and boundary-mapping architecture contracts."""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from pathlib import Path

from _verification_common import PRODUCTION_ROOT, fail_or_pass, parse_python, relative

_REVIEW_LINE_LIMIT = 430
_DIRECT_MODULE_LIMIT = 10
_LEGACY_MODULE_DOC_FRAGMENTS = (
    "compatibility facade",
    "compatibility imports",
    "composite compatibility",
    "deprecated mcp backend gateway",
    "legacy facade",
)
_GENERIC_MODULE_NAMES = frozenset(
    {
        "common.py",
        "helpers.py",
        "manager.py",
        "misc.py",
        "models.py",
        "schema.py",
        "types.py",
        "utils.py",
    }
)


def _production_files() -> tuple[Path, ...]:
    """Return production Python modules in deterministic order."""
    return tuple(
        path
        for path in sorted(PRODUCTION_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _terminal_call_name(node: ast.expr) -> str:
    """Return the terminal name of a simple callable expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _contains_model_dump(node: ast.AST) -> bool:
    """Return whether an expression contains a Pydantic model_dump call."""
    return any(
        isinstance(candidate, ast.Call)
        and _terminal_call_name(candidate.func) == "model_dump"
        for candidate in ast.walk(node)
    )


def _check_package_density(violations: list[str]) -> None:
    """Reject packages that exceed the direct-module review threshold."""
    directories = (
        PRODUCTION_ROOT,
        *(
            path
            for path in PRODUCTION_ROOT.rglob("*")
            if path.is_dir() and "__pycache__" not in path.parts
        ),
    )
    for directory in sorted(directories):
        direct_modules = sum(
            1 for path in directory.glob("*.py") if path.name != "__init__.py"
        )
        if direct_modules <= _DIRECT_MODULE_LIMIT:
            continue
        package = directory.relative_to(PRODUCTION_ROOT.parent).as_posix()
        violations.append(
            f"{package}: package has {direct_modules} direct modules, exceeding the {_DIRECT_MODULE_LIMIT}-module review trigger; split by concept/responsibility"
        )


def _check_exact_duplicate_modules(
    files: tuple[Path, ...],
    violations: list[str],
) -> None:
    """Reject byte-identical production modules outside package initializers."""
    paths_by_digest: defaultdict[str, list[Path]] = defaultdict(list)
    for path in files:
        if path.name == "__init__.py":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        paths_by_digest[digest].append(path)
    for paths in paths_by_digest.values():
        if len(paths) < 2:
            continue
        rendered_paths = ", ".join(relative(path) for path in sorted(paths))
        violations.append(
            f"{rendered_paths}: byte-identical production modules forbidden; keep one canonical owner"
        )


def _check_module(path: Path, violations: list[str]) -> None:
    """Reject ambiguous names, legacy facades, oversized modules, and round-trips."""
    rel = relative(path)
    if path.name in _GENERIC_MODULE_NAMES:
        violations.append(
            f"{rel}: generic module name forbidden; use a concept-specific Clean Architecture role name"
        )
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    if line_count > _REVIEW_LINE_LIMIT:
        violations.append(
            f"{rel}: module has {line_count} lines, exceeding the {_REVIEW_LINE_LIMIT}-line architecture review trigger; split responsibilities"
        )
    tree = parse_python(path)
    module_docstring = (ast.get_docstring(tree, clean=True) or "").casefold()
    if any(fragment in module_docstring for fragment in _LEGACY_MODULE_DOC_FRAGMENTS):
        violations.append(
            f"{rel}: legacy compatibility/deprecation facade forbidden; import canonical owner modules"
        )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _terminal_call_name(node.func) == "model_validate" and any(
            _contains_model_dump(argument) for argument in node.args
        ):
            violations.append(
                f"{rel}:{node.lineno}: model_dump() followed by model_validate() forbidden; use a typed mapper"
            )
        violations.extend(
            f"{rel}:{node.lineno}: spreading model_dump() into another boundary constructor forbidden; map typed fields explicitly"
            for keyword in node.keywords
            if keyword.arg is None and _contains_model_dump(keyword.value)
        )


def main() -> int:
    """Run the fail-closed Alexandria architecture verifier."""
    violations: list[str] = []
    files = _production_files()
    _check_package_density(violations)
    _check_exact_duplicate_modules(files, violations)
    for path in files:
        _check_module(path, violations)
    return fail_or_pass("architecture-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
