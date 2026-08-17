"""CLI package execution contract tests."""

from __future__ import annotations

import subprocess
import sys


def test_cli_package_is_executable_from_backend_directory() -> None:
    """The repo shim should be able to run ``python -m app.cli``."""
    completed = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "heterarchy-alexandria command line client" in completed.stdout
    assert "No module named app.cli.__main__" not in completed.stderr
