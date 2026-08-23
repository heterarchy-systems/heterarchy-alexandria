"""Guardrail integration for broad types and local import exceptions."""

from __future__ import annotations

from app.shared.guardrails.check_broad_types import collect_failures as broad_failures
from app.shared.guardrails.check_getattr_usage import (
    collect_failures as dynamic_attribute_failures,
)
from app.shared.guardrails.check_docstring_contracts import (
    collect_failures as docstring_failures,
)
from app.shared.guardrails.check_lazy_import_usage import (
    collect_failures as lazy_import_failures,
)
from app.shared.guardrails.check_protocol_usage import (
    collect_failures as protocol_failures,
)


def test_production_annotations_avoid_unjustified_broad_types() -> None:
    """Ensure production type annotations satisfy the broad-type harness."""
    assert broad_failures() == []


def test_local_imports_have_explicit_boundary_justification() -> None:
    """Ensure production local imports are explicitly justified."""
    assert lazy_import_failures() == []


def test_dynamic_attribute_access_obeys_repository_policy() -> None:
    """Reject forbidden dynamic attribute mutation and unjustified reads."""
    assert dynamic_attribute_failures() == []


def test_all_production_callables_have_complete_docstrings() -> None:
    """Require Google-style callable documentation throughout production code."""
    assert docstring_failures() == []


def test_protocols_are_limited_to_explicit_structural_seams() -> None:
    """Require managed ports to use ABC instead of implicit Protocol typing."""
    assert protocol_failures() == []


def test_from_import_paths_do_not_depend_on_accidental_reexports() -> None:
    """Require from-imports to target the module that owns each symbol."""
    import ast
    from pathlib import Path

    roots = (Path("app"), Path("tests"))
    python_paths = [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]

    module_defs: dict[str, set[str]] = {}
    module_imports: dict[str, set[str]] = {}

    def module_name(path: Path) -> str:
        module_parts = path.with_suffix("").parts
        if module_parts[-1] == "__init__":
            module_parts = module_parts[:-1]
        return ".".join(module_parts)

    for path in python_paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        defined_names: set[str] = set()
        imported_names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                defined_names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined_names.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined_names.add(node.target.id)
            elif isinstance(node, ast.Import):
                imported_names.update(
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                imported_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
        module_defs[module_name(path)] = defined_names
        module_imports[module_name(path)] = imported_names

    failures: list[str] = []
    for path in python_paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.ImportFrom)
                or node.module is None
                or node.level
            ):
                continue
            imported_module = node.module
            if not imported_module.startswith(("app.", "tests.")):
                continue
            if imported_module not in module_defs:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if (
                    alias.name in module_imports[imported_module]
                    and alias.name not in module_defs[imported_module]
                ):
                    failures.append(
                        f"{path}:{node.lineno}: {imported_module}.{alias.name}"
                    )
    assert failures == []


def test_mcp_gateway_does_not_import_skill_evidence_http_schema() -> None:
    """Keep skill evidence JSON normalization outside Librarian HTTP schemas."""
    from pathlib import Path

    gateway = Path("app/mcp_server/tools/skills/skill_backend_gateway.py").read_text()
    policy = Path("app/mcp_server/tools/backend_gateway_policy.py").read_text()

    assert "SkillAcquisitionEvidenceItemRequest" not in gateway
    assert "SkillAcquisitionEvidenceItemRequest" not in policy
