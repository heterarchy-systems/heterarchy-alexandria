"""Verify Alexandria ORM-owned production database contracts."""

from __future__ import annotations

import ast
from pathlib import Path

from _verification_common import BACKEND_ROOT, fail_or_pass, relative

_DATABASE_MODULE = BACKEND_ROOT / "app" / "shared" / "infrastructure" / "database.py"
_PRODUCTION_DATABASE_ROOTS = (
    BACKEND_ROOT / "app",
    BACKEND_ROOT / "migrations",
)


def _call_terminal_name(node: ast.expr) -> str:
    """Return the terminal name of a simple call or attribute expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _database_module_contracts(violations: list[str]) -> None:
    """Verify SQLAlchemy metadata owns the runtime schema foundation."""
    tree = ast.parse(
        _DATABASE_MODULE.read_text(encoding="utf-8"),
        filename=str(_DATABASE_MODULE),
    )
    declarative_base_seen = any(
        isinstance(node, ast.ClassDef)
        and any(_call_terminal_name(base) == "DeclarativeBase" for base in node.bases)
        for node in tree.body
    )
    if not declarative_base_seen:
        violations.append(
            f"{relative(_DATABASE_MODULE)}: ORM base must inherit SQLAlchemy DeclarativeBase"
        )
    metadata_create_seen = any(
        isinstance(node, ast.Attribute)
        and node.attr == "create_all"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "metadata"
        for node in ast.walk(tree)
    )
    if not metadata_create_seen:
        violations.append(
            f"{relative(_DATABASE_MODULE)}: runtime schema bootstrap must use ORM metadata.create_all"
        )


def _production_sql_files() -> tuple[Path, ...]:
    """Return standalone SQL files from production and migration roots."""
    return tuple(
        path
        for root in _PRODUCTION_DATABASE_ROOTS
        for path in sorted(root.rglob("*.sql"))
        if "__pycache__" not in path.parts
    )


def main() -> int:
    """Run the fail-closed Alexandria database contract verifier."""
    violations = [
        f"{relative(path)}: standalone production SQL file forbidden; use typed SQLAlchemy/Alembic Python operations"
        for path in _production_sql_files()
    ]
    _database_module_contracts(violations)
    return fail_or_pass("database-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
