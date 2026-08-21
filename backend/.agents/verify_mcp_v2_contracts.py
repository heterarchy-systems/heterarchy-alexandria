#!/usr/bin/env python3
"""Verify the installed official MCP SDK v2 runtime contract."""

from __future__ import annotations

import inspect
import re
import sys
from importlib.metadata import distributions
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"
LOCK_PATH = BACKEND_ROOT / "uv.lock"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _installed_mcp_version() -> str:
    """Return the single valid installed MCP distribution version.

    Returns:
        Version text from the unique installed MCP distribution.

    Raises:
        RuntimeError: If MCP metadata is missing, invalid, or ambiguous.
    """
    versions = tuple(
        version_text
        for distribution in distributions(name="mcp")
        if isinstance(
            version_text := distribution.metadata.get("Version"),
            str,
        )
        and version_text
    )
    if len(versions) != 1:
        raise RuntimeError(
            "expected one valid installed MCP distribution, "
            f"found versions={versions!r}"
        )
    return versions[0]


def _build_runtime_server() -> object:
    """Build the production MCP server through its zero-argument path.

    Returns:
        Runtime object produced by the Alexandria MCP composition root.

    Raises:
        RuntimeError: If the composition root is missing or requires arguments.
    """
    from app.mcp_server import server_runtime

    builder = server_runtime.build_mcp_server
    signature = inspect.signature(builder)
    required = [
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    ]
    if required:
        raise RuntimeError(
            "build_mcp_server must retain a zero-argument verification path; "
            f"required={required}"
        )
    return builder()


def main() -> int:
    """Fail unless dependency, lock, and runtime agree on official MCP v2."""
    from mcp.server import MCPServer

    errors: list[str] = []
    installed_version = "unknown"
    try:
        installed_version = _installed_mcp_version()
        if installed_version.split(".", 1)[0] != "2":
            errors.append(
                f"installed mcp must be major version 2, found {installed_version}"
            )
    except RuntimeError as exc:
        errors.append(f"installed MCP metadata is invalid: {exc}")

    project = PYPROJECT_PATH.read_text(encoding="utf-8")
    if re.search(r'["\']mcp>=2,<3["\']', project, flags=re.IGNORECASE) is None:
        errors.append("pyproject.toml must constrain mcp to >=2,<3")

    lock = LOCK_PATH.read_text(encoding="utf-8")
    if 'name = "mcp"\nversion = "2.' not in lock:
        errors.append("uv.lock must resolve MCP major version 2")

    try:
        runtime_server = _build_runtime_server()
        if not isinstance(runtime_server, MCPServer):
            errors.append("build_mcp_server must return an official MCPServer instance")
    except Exception as exc:
        errors.append(
            f"MCP v2 runtime verification failed: {type(exc).__name__}: {exc}"
        )

    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"mcp-v2-contracts: PASS ({installed_version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
