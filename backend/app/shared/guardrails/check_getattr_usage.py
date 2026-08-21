"""AST-based dynamic attribute access guard."""

from __future__ import annotations

import ast
from pathlib import Path

from app.shared.guardrails._common import (
    DYNAMIC_ATTRIBUTE_JUSTIFICATION_MARKERS,
    has_justification,
    iter_guard_target_paths,
    parse_module,
)

FORBIDDEN_DYNAMIC_ATTRIBUTE_CALLS = {"getattr", "hasattr", "setattr"}


class DynamicAttributeVisitor(ast.NodeVisitor):
    """Collect dynamic attribute access violations."""

    def __init__(self, path: Path, lines: list[str]) -> None:
        """Initialize dynamic attribute visitor.

        Args:
            path: See function signature.
            lines: See function signature.

        Returns:
            None.
        """
        self._path = path
        self._lines = lines
        self.failures: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Validate dynamic attribute calls and check for justification.

        Args:
            node: See function signature.

        Returns:
            None.
        """
        if not isinstance(node.func, ast.Name):
            self.generic_visit(node)
            return

        call_name = node.func.id
        if call_name not in FORBIDDEN_DYNAMIC_ATTRIBUTE_CALLS:
            self.generic_visit(node)
            return

        if has_justification(
            lines=self._lines,
            lineno=node.lineno,
            markers=DYNAMIC_ATTRIBUTE_JUSTIFICATION_MARKERS,
        ):
            self.generic_visit(node)
            return

        self.failures.append(
            f"{self._path}:{node.lineno}: {call_name} usage without justification"
        )
        self.generic_visit(node)


def collect_failures(backend_root: Path | None = None) -> list[str]:
    """Collect all dynamic attribute access guard violations.

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
        visitor = DynamicAttributeVisitor(path=path, lines=lines)
        visitor.visit(parse_module(path))
        failures.extend(visitor.failures)
    return failures


def ensure_clean(backend_root: Path | None = None) -> None:
    """Raise an error if any dynamic attribute violations are found.

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
    message = f"dynamic attribute usage check failed:\n{rendered}"
    raise RuntimeError(message)


def main() -> int:
    """CLI entry point to run dynamic attribute guard.

    Args:
        None.

    Returns:
        Return value.
    """
    failures = collect_failures()
    if failures:
        print("dynamic attribute usage check failed:\n")
        for failure in failures:
            print(failure)
        return 1

    print("dynamic attribute usage check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
