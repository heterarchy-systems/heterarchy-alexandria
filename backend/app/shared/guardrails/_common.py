"""Shared guardrail utility helpers."""

from __future__ import annotations

import ast
from pathlib import Path

TYPE_JUSTIFICATION_MARKERS = (
    "Any justified:",
    "Broad type justified:",
)
DYNAMIC_ATTRIBUTE_JUSTIFICATION_MARKERS = (
    "getattr justified:",
    "hasattr justified:",
    "dynamic attribute justified:",
)
LAZY_IMPORT_JUSTIFICATION_MARKERS = (
    "lazy import justified:",
    "local import justified:",
)


def resolve_backend_root(reference_file: Path, backend_root: Path | None) -> Path:
    """Resolve backend root used by guard checks.

    Args:
        reference_file: See function signature.
        backend_root: See function signature.

    Returns:
        Return value.
    """
    return backend_root or reference_file.resolve().parents[3]


def should_check(path: Path, backend_root: Path) -> bool:
    """Determine whether a path should be included in guard checks.

    Args:
        path: See function signature.
        backend_root: See function signature.

    Returns:
        Return value.
    """
    try:
        relative = path.relative_to(backend_root)
    except ValueError:
        return False
    return (
        path.suffix == ".py"
        and relative.parts[0] == "app"
        and "tests" not in relative.parts
        and not (
            relative.parts[:3] == ("app", "shared", "guardrails")
            and path.name.startswith("check_")
        )
    )


def iter_guard_target_paths(
    reference_file: Path, backend_root: Path | None = None
) -> list[Path]:
    """Collect backend app files that should be scanned by guards.

    Args:
        reference_file: See function signature.
        backend_root: See function signature.

    Returns:
        Return value.
    """
    resolved_root = resolve_backend_root(reference_file, backend_root)
    return [
        path
        for path in resolved_root.rglob("*.py")
        if should_check(path, backend_root=resolved_root)
    ]


def parse_module(path: Path) -> ast.AST:
    """Parse a Python file into an AST.

    Args:
        path: See function signature.

    Returns:
        Return value.
    """
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def has_justification(
    lines: list[str],
    lineno: int,
    markers: tuple[str, ...],
) -> bool:
    """Check for nearby justification comment around the target line.

    Args:
        lines: See function signature.
        lineno: See function signature.
        markers: See function signature.

    Returns:
        Return value.
    """
    current_line = lines[lineno - 1]
    if any(marker in current_line for marker in markers):
        return True

    index = lineno - 2
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped:
            index -= 1
            continue
        if stripped.startswith("#"):
            if any(marker in stripped for marker in markers):
                return True
            index -= 1
            continue
        break
    return False
