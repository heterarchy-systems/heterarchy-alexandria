"""MCP and Makefile boundary tests."""

from __future__ import annotations

from pathlib import Path

OPERATIONAL_TARGETS = ("mcp-smoke-tools",)


def test_makefile_keeps_only_build_and_ci_targets() -> None:
    """Makefile should stay focused on install, smoke, and CI workflows."""
    makefile = Path(__file__).resolve().parents[2] / "Makefile"
    text = makefile.read_text()

    assert (
        ".PHONY: install-local format_check type_checking cli_smoke test ci benchmark_check mechanical_check"
        in text
    )
    assert (
        "ci: format_check type_checking cli_smoke test benchmark_check mechanical_check"
        in text
    )
    assert "cli_smoke:" in text
    assert "uv sync --no-editable --reinstall-package heterarchy-alexandria" in text
    assert "uv run --isolated --with . heterarchy-alexandria --help >/dev/null" in text
    assert "LOAD_LOCAL_ENV" not in text
    assert "PROJECT ?=" not in text
    assert "REVIEW_LIMIT ?=" not in text
    for target in OPERATIONAL_TARGETS:
        assert f"\n{target}:" not in text


def test_ci_gate_uses_ephemeral_postgres_without_runtime_dns_dependency() -> None:
    """Local pre-push and GitHub Actions should share a portable PostgreSQL gate."""
    backend_root = Path(__file__).resolve().parents[2]
    repository_root = backend_root.parent
    makefile_text = (backend_root / "Makefile").read_text()
    runner = backend_root / "scripts" / "run-postgres-tests.sh"
    runner_text = runner.read_text()
    pre_commit_text = (repository_root / ".pre-commit-config.yaml").read_text()
    workflow_text = (
        repository_root / ".github" / "workflows" / "backend.yml"
    ).read_text()

    assert "./scripts/run-postgres-tests.sh" in makefile_text
    assert runner.is_file()
    assert runner.stat().st_mode & 0o111
    assert "--publish 127.0.0.1::5432" in runner_text
    assert "docker rm -f" in runner_text
    assert "@127.0.0.1:${postgres_port}/" in runner_text
    assert "unset VIRTUAL_ENV" in pre_commit_text
    assert "run: make ci" in workflow_text


def test_package_cli_declares_direct_typer_dependency() -> None:
    """Typer CLI package should not rely on transitive dependency exposure."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text()

    assert '"typer>=0.25.1,<1.0.0"' in text


def test_package_cli_mcp_modules_are_explicit_packages() -> None:
    """Installed CLI should not depend on implicit namespace package discovery."""
    backend_root = Path(__file__).resolve().parents[2]

    assert (backend_root / "app" / "__init__.py").is_file()
    cli_root = backend_root / "app" / "cli"
    assert (cli_root / "__init__.py").is_file()
    assert (cli_root / "main.py").is_file()
    assert (cli_root / "mcp_server_commands.py").is_file()
    assert (cli_root / "maintenance_workflow_commands.py").is_file()
    assert (cli_root / "memory_steward_commands.py").is_file()
    assert not (cli_root / "vault_maintenance_commands.py").exists()
    assert (cli_root / "maintenance_command_context.py").is_file()
    assert (cli_root / "maintenance_gateway.py").is_file()
    assert (cli_root / "type_validate" / "command_options.py").is_file()
    assert (cli_root / "type_validate" / "maintenance_payload_schemas.py").is_file()
    assert not (cli_root / "mcp.py").exists()
    assert not (cli_root / "options.py").exists()
    assert (backend_root / "app" / "mcp_server" / "__init__.py").is_file()
    assert (
        backend_root / "app" / "mcp_server" / "type_validate" / "mcp_transport_enums.py"
    ).is_file()
    assert (backend_root / "app" / "mcp_server" / "tools" / "__init__.py").is_file()
    assert (backend_root / "app" / "mcp_server" / "server_runtime.py").is_file()
    assert (
        backend_root / "app" / "mcp_server" / "tools" / "backend_gateway_policy.py"
    ).is_file()
