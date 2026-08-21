"""AST-based broad type usage guard."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.shared.guardrails._common import (
    TYPE_JUSTIFICATION_MARKERS,
    has_justification,
    iter_guard_target_paths,
    parse_module,
)

ANY_PATTERN = re.compile(r"\bAny\b")
OBJECT_PATTERN = re.compile(r"\bobject\b")
BROAD_DICT_PATTERN = re.compile(r"\b(?:dict|Mapping)\[[^\]]*\b(?:Any|object)\b[^\]]*\]")


class BroadTypeVisitor(ast.NodeVisitor):
    """Collect broad type usage inside type annotations."""

    def __init__(self, path: Path, lines: list[str]) -> None:
        """Initialize the broad type visitor.

        Args:
            path: See function signature.
            lines: See function signature.

        Returns:
            None.
        """
        self._path = path
        self._lines = lines
        self.failures: list[str] = []

    def _check_type_node(self, node: ast.expr | ast.arg | None) -> None:
        """Inspect one type node and record broad type violations.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        if node is None:
            return
        rendered = ast.unparse(node)
        has_any = ANY_PATTERN.search(rendered) is not None
        has_object = OBJECT_PATTERN.search(rendered) is not None
        has_broad_dict = BROAD_DICT_PATTERN.search(rendered) is not None
        if not has_any and not has_object and not has_broad_dict:
            return
        if has_justification(
            lines=self._lines,
            lineno=node.lineno,
            markers=TYPE_JUSTIFICATION_MARKERS,
        ):
            return
        if has_broad_dict:
            self.failures.append(
                f"{self._path}:{node.lineno}: broad dictionary type without justification"
            )
            return
        self.failures.append(
            f"{self._path}:{node.lineno}: broad type without justification"
        )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Check annotated assignment type hints.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_type_node(node.annotation)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        """Check function argument type hints.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_type_node(node.annotation)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check sync function return annotations.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_type_node(node.returns)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function return annotations.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_type_node(node.returns)
        self.generic_visit(node)

    def visit_TypeAlias(self, node: ast.TypeAlias) -> None:
        """Check type alias definitions.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        self._check_type_node(node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect ``cast`` call type arguments.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        if isinstance(node.func, ast.Name) and node.func.id == "cast" and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.expr):
                self._check_type_node(first_arg)
        self.generic_visit(node)


def collect_failures(backend_root: Path | None = None) -> list[str]:
    """Collect broad type guard violations.

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
        visitor = BroadTypeVisitor(path=path, lines=lines)
        visitor.visit(parse_module(path))
        failures.extend(visitor.failures)
    return failures


def ensure_clean(backend_root: Path | None = None) -> None:
    """Raise an error if any broad type violations are found.

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
    message = f"Broad type usage check failed:\n{rendered}"
    raise RuntimeError(message)


def main() -> int:
    """CLI entry point to run broad type guard.

    Args:
        None.

    Returns:
        Return value.
    """
    failures = collect_failures()
    if failures:
        print("Broad type usage check failed:\n")
        for failure in failures:
            print(failure)
        return 1

    print("Broad type usage check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
