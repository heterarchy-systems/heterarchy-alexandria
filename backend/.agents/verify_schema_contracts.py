"""Verify canonical strict Pydantic v2 schema contracts."""

from __future__ import annotations

import ast

from _verification_common import (
    PRODUCTION_ROOT,
    base_name,
    call_name,
    fail_or_pass,
    parse_python,
    production_python_files,
    relative,
)

_CANONICAL = PRODUCTION_ROOT / "shared" / "schemas" / "common_schemas.py"
_REQUIRED_CONFIG = {
    "extra": "forbid",
    "frozen": True,
    "strict": True,
    "use_enum_values": True,
    "validate_default": True,
}


def _has_described_field(annotation: ast.expr) -> bool:
    return any(
        isinstance(node, ast.Call) and call_name(node) == "described_field"
        for node in ast.walk(annotation)
    )


def _verify_canonical_base(violations: list[str]) -> None:
    tree = parse_python(_CANONICAL)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    for class_name in ("StrictSchemaModel", "StrictRootSchemaModel"):
        node = classes.get(class_name)
        if node is None:
            violations.append(f"{relative(_CANONICAL)}: missing {class_name}")
            continue
        config = next(
            (
                statement.value
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "model_config"
                    for target in statement.targets
                )
                and isinstance(statement.value, ast.Call)
                and call_name(statement.value) == "ConfigDict"
            ),
            None,
        )
        if config is None:
            violations.append(
                f"{relative(_CANONICAL)}:{node.lineno}: {class_name} missing ConfigDict"
            )
            continue
        values = {
            keyword.arg: keyword.value
            for keyword in config.keywords
            if keyword.arg is not None
        }
        required = dict(_REQUIRED_CONFIG)
        if class_name == "StrictRootSchemaModel":
            required.pop("extra")
        for key, expected in required.items():
            value = values.get(key)
            if not isinstance(value, ast.Constant) or value.value != expected:
                violations.append(
                    f"{relative(_CANONICAL)}:{node.lineno}: {class_name}.{key} must equal {expected!r}"
                )
    helper = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "described_field"
        ),
        None,
    )
    if helper is None:
        violations.append(f"{relative(_CANONICAL)}: missing described_field")
    else:
        parameter_names = {
            argument.arg
            for argument in [
                *helper.args.posonlyargs,
                *helper.args.args,
                *helper.args.kwonlyargs,
            ]
        }
        violations.extend(
            f"{relative(_CANONICAL)}:{helper.lineno}: described_field must not accept {banned}"
            for banned in ("default", "default_factory")
            if banned in parameter_names
        )


def main() -> int:
    """Run the fail-closed Pydantic schema verifier."""
    violations: list[str] = []
    _verify_canonical_base(violations)
    for path in production_python_files():
        tree = parse_python(path)
        rel = relative(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("pydantic.v1"):
                    violations.append(
                        f"{rel}:{node.lineno}: pydantic.v1 import forbidden"
                    )
            if isinstance(node, ast.Call):
                name = call_name(node)
                if name == "Field" and path != _CANONICAL:
                    violations.append(
                        f"{rel}:{node.lineno}: direct Field() call forbidden"
                    )
                if name == "described_field":
                    if not node.args or not isinstance(node.args[0], ast.Constant):
                        violations.append(
                            f"{rel}:{node.lineno}: described_field requires literal description"
                        )
                    elif (
                        not isinstance(node.args[0].value, str)
                        or not node.args[0].value.strip()
                    ):
                        violations.append(
                            f"{rel}:{node.lineno}: described_field description must be non-empty"
                        )
            if isinstance(node, ast.ClassDef):
                bases = {base_name(base) for base in node.bases}
                if path != _CANONICAL and bases.intersection(
                    {"BaseModel", "RootModel"}
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: direct Pydantic base on {node.name}"
                    )
                if "StrictSchemaModel" in bases:
                    for statement in node.body:
                        if not isinstance(statement, ast.AnnAssign) or not isinstance(
                            statement.target, ast.Name
                        ):
                            continue
                        field_name = statement.target.id
                        if field_name.startswith("_") or field_name == "model_config":
                            continue
                        annotation_text = ast.unparse(statement.annotation)
                        if "ClassVar" in annotation_text:
                            continue
                        if not _has_described_field(statement.annotation):
                            violations.append(
                                f"{rel}:{statement.lineno}: {node.name}.{field_name} missing described_field metadata"
                            )
                for statement in node.body:
                    if not isinstance(
                        statement, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        continue
                    for decorator in statement.decorator_list:
                        name = (
                            call_name(decorator)
                            if isinstance(decorator, ast.Call)
                            else base_name(decorator)
                        )
                        if name in {"validator", "root_validator"}:
                            violations.append(
                                f"{rel}:{statement.lineno}: Pydantic v1 validator API forbidden"
                            )
    return fail_or_pass("schema-contracts", violations)


if __name__ == "__main__":
    raise SystemExit(main())
