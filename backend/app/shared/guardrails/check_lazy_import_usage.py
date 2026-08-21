"""AST-based lazy import guard."""

from __future__ import annotations

import ast
from pathlib import Path

from app.shared.guardrails._common import (
    LAZY_IMPORT_JUSTIFICATION_MARKERS,
    has_justification,
    iter_guard_target_paths,
    parse_module,
)

_DYNAMIC_IMPORT_CALLS = {"__import__"}


class LazyImportVisitor(ast.NodeVisitor):
    """Collect improper in-scope imports and dynamic import calls.

    The seven public methods are required ``ast.NodeVisitor`` hooks rather than
    independent application responsibilities.
    """

    def __init__(self, path: Path, lines: list[str]) -> None:
        """Initialize the lazy import visitor.

        Args:
            path: See function signature.
            lines: See function signature.

        Returns:
            None.
        """
        self._path = path
        self._lines = lines
        self._scope_depth = 0
        self._type_checking_depth = 0
        self.failures: list[str] = []

    def visit_If(self, node: ast.If) -> None:
        """Allow TYPE_CHECKING branches, inspect all other branches.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        if self._is_type_checking_guard(node.test):
            self._type_checking_depth += 1
            for child in node.body:
                self.visit(child)
            self._type_checking_depth -= 1
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Inspect imports inside function scope.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Inspect imports inside async function scope.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Inspect imports inside class body.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        """Inspect a regular local import statement.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_local_import(node=node, label="local import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Inspect a local import-from statement.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_local_import(node=node, label="local import-from")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect dynamic import call expressions.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        call_name = self._call_name(node.func)
        if call_name in _DYNAMIC_IMPORT_CALLS or call_name == "importlib.import_module":
            self._add_failure_if_unjustified(
                lineno=node.lineno,
                label=f"dynamic import call `{call_name}`",
            )
        self.generic_visit(node)

    def _check_local_import(
        self, node: ast.Import | ast.ImportFrom, label: str
    ) -> None:
        """Check whether a local import violates the lazy-import policy.

        Args:
            node: See function signature.
            label: See function signature.

        Returns:
            None.
        """
        if self._type_checking_depth > 0:
            return
        if self._scope_depth == 0:
            return
        self._add_failure_if_unjustified(lineno=node.lineno, label=label)

    def _add_failure_if_unjustified(self, lineno: int, label: str) -> None:
        """Add a lazy-import violation unless a justification marker exists.

        Args:
            lineno: See function signature.
            label: See function signature.

        Returns:
            None.
        """
        if has_justification(
            lines=self._lines,
            lineno=lineno,
            markers=LAZY_IMPORT_JUSTIFICATION_MARKERS,
        ):
            return
        self.failures.append(f"{self._path}:{lineno}: {label} without justification")

    def _is_type_checking_guard(self, node: ast.expr) -> bool:
        """Check whether an if-condition is a TYPE_CHECKING guard.

        Args:
            node: See function signature.

        Returns:
            Return value.
        """
        if isinstance(node, ast.Name):
            return node.id == "TYPE_CHECKING"
        if isinstance(node, ast.Attribute):
            return node.attr == "TYPE_CHECKING"
        return False

    def _call_name(self, node: ast.expr) -> str | None:
        """Resolve call target to a string when possible.

        Args:
            node: See function signature.

        Returns:
            Return value.
        """
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        return None


def collect_failures(backend_root: Path | None = None) -> list[str]:
    """Collect lazy import guard violations.

    Args:
        backend_root: See function signature.

    Returns:
        Return value.
    """
    failures: list[str] = []
    for path in iter_guard_target_paths(
        reference_file=Path(__file__), backend_root=backend_root
    ):
        lines = path.read_text(encoding="utf-8").splitlines()
        visitor = LazyImportVisitor(path=path, lines=lines)
        visitor.visit(parse_module(path))
        failures.extend(visitor.failures)
    return failures


def ensure_clean(backend_root: Path | None = None) -> None:
    """Raise an error if lazy import violations are found.

    Args:
        backend_root: See function signature.

    Returns:
        None.
    """
    failures = collect_failures(backend_root)
    if not failures:
        return

    rendered = "\n".join(failures[:20])
    if len(failures) > 20:
        rendered = f"{rendered}\n... and {len(failures) - 20} more"
    message = f"lazy import usage check failed:\n{rendered}"
    raise RuntimeError(message)


def main() -> int:
    """CLI entry point for the lazy import guard.

    Args:
        None.

    Returns:
        Return value.
    """
    failures = collect_failures()
    if failures:
        print("lazy import usage check failed:\n")
        for failure in failures:
            print(failure)
        return 1

    print("lazy import usage check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
