"""Verify shared, MCP, and composition dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

from _verification_common import PRODUCTION_ROOT, fail_or_pass, parse_python, relative

_FEATURES = frozenset({"connections", "librarian", "memory", "obsidian", "operations"})
_MCP_FORBIDDEN_LAYERS = frozenset({"application", "infrastructure"})


def _imported_modules(tree: ast.Module) -> tuple[tuple[int, str], ...]:
    """Collect imported module names with source line numbers."""
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
    return tuple(imports)


def _is_mcp_implementation_import(module: str) -> bool:
    """Return whether MCP imports a backend implementation-owned module."""
    parts = module.split(".")
    if len(parts) >= 2 and parts[:2] == ["app", "platform"]:
        return True
    if len(parts) < 4 or parts[0] != "app" or parts[1] not in _FEATURES:
        return False
    layer = parts[2]
    if layer in _MCP_FORBIDDEN_LAYERS:
        return True
    return layer == "interface" and parts[3] != "schemas"


def _check_shared_boundary(
    path: Path,
    imports: tuple[tuple[int, str], ...],
    violations: list[str],
) -> None:
    """Reject shared code that depends on feature or platform modules."""
    for lineno, module in imports:
        if module.startswith("app.") and not module.startswith("app.shared"):
            violations.append(
                f"{relative(path)}:{lineno}: shared imports non-shared module {module!r}"
            )


def _check_mcp_boundary(
    path: Path,
    imports: tuple[tuple[int, str], ...],
    violations: list[str],
) -> None:
    """Reject MCP imports of implementation and non-schema interface layers."""
    for lineno, module in imports:
        if _is_mcp_implementation_import(module):
            violations.append(
                f"{relative(path)}:{lineno}: MCP imports backend implementation boundary {module!r}; use MCP/shared protocol contracts and HTTP gateways"
            )


def main() -> int:
    """Run the fail-closed Alexandria boundary verifier."""
    violations: list[str] = []
    for path in sorted(PRODUCTION_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        imports = _imported_modules(parse_python(path))
        path_parts = path.relative_to(PRODUCTION_ROOT).parts
        if path_parts and path_parts[0] == "shared":
            _check_shared_boundary(path, imports, violations)
        if path_parts and path_parts[0] == "mcp_server":
            _check_mcp_boundary(path, imports, violations)
    return fail_or_pass("boundary-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
