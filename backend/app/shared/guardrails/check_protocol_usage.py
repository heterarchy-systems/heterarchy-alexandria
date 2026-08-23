"""AST-based ABC-first managed port policy guard."""

from __future__ import annotations

import ast
from pathlib import Path

from app.shared.guardrails._common import iter_guard_target_paths, parse_module

_STRUCTURAL_SEAM_MARKER = "protocol-contract: structural-seam"


def _inherits_protocol(node: ast.ClassDef) -> bool:
    """Return whether a class directly inherits Protocol.

    Args:
        node: Class definition being inspected.

    Returns:
        True when Protocol is one of the direct bases.
    """
    return any(
        (isinstance(base, ast.Name) and base.id == "Protocol")
        or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
        for base in node.bases
    )


def _has_structural_seam_marker(node: ast.ClassDef, lines: list[str]) -> bool:
    """Return whether a Protocol declares its structural-seam exception.

    Args:
        node: Protocol class definition being inspected.
        lines: Source lines for adjacent-comment inspection.

    Returns:
        True when the explicit structural-seam marker is present.
    """
    docstring = ast.get_docstring(node, clean=False) or ""
    if _STRUCTURAL_SEAM_MARKER in docstring:
        return True
    index = node.lineno - 2
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped:
            index -= 1
            continue
        if stripped.startswith("#"):
            if _STRUCTURAL_SEAM_MARKER in stripped:
                return True
            index -= 1
            continue
        break
    return False


def collect_failures(backend_root: Path | None = None) -> list[str]:
    """Collect Protocol declarations that should be managed ABC ports.

    Args:
        backend_root: Explicit backend root for tests or alternate invocations.

    Returns:
        Protocol declarations lacking the structural-seam exception marker.
    """
    failures: list[str] = []
    for path in iter_guard_target_paths(Path(__file__), backend_root=backend_root):
        lines = path.read_text(encoding="utf-8").splitlines()
        tree = parse_module(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not _inherits_protocol(node):
                continue
            if _has_structural_seam_marker(node, lines):
                continue
            failures.append(
                f"{path}:{node.lineno}:{node.name}: managed Protocol requires ABC or explicit structural-seam marker"
            )
    return failures


def main() -> int:
    """Run the ABC-first Protocol policy guard.

    Returns:
        Process exit status for the Protocol policy.
    """
    failures = collect_failures()
    if failures:
        print("Protocol policy check failed:")
        for failure in failures:
            print(failure)
        return 1
    print("Protocol policy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
