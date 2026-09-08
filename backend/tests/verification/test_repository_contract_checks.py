"""Exercise repository contract checks without a provisioned agent bundle."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

VERIFICATION_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts/verification"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    shutil.copytree(
        VERIFICATION_DIRECTORY,
        tmp_path / "backend/scripts/verification",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    source = tmp_path / "backend/app"
    source.mkdir()
    (source / "example.py").write_text(
        "def identity(value: str) -> str:\n    return value\n", encoding="utf-8"
    )
    return tmp_path


def run_checks(
    checkout: Path, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(checkout / "backend/scripts/verification/verify_contracts.py"),
        ],
        cwd=cwd or checkout,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("working_directory", [".", "backend"])
def test_checks_pass_without_agent_bundle(
    checkout: Path, working_directory: str
) -> None:
    assert not (checkout / ".agents").exists()
    result = run_checks(checkout, checkout / working_directory)
    assert result.returncode == 0, result.stdout + result.stderr
    for label in (
        "type-contracts",
        "dynamic-attribute-contracts",
        "async-contracts",
        "schema-contracts",
        "fastapi-contracts",
        "dependency-injector-contracts",
    ):
        assert f"{label}: PASS" in result.stdout


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    [
        (
            "def missing_annotation(value):\n    return value\n",
            "has no return annotation",
        ),
        ("value = getattr(object(), 'name')\n", "is forbidden in production Python"),
        (
            "import time\nasync def pause() -> None:\n    time.sleep(1)\n",
            "time.sleep() blocks the event loop",
        ),
        ("from pydantic.v1 import BaseModel\n", "pydantic.v1 compatibility import"),
        (
            "from fastapi.responses import ORJSONResponse\n",
            "deprecated FastAPI ORJSONResponse",
        ),
        (
            "from dependency_injector import providers\nvalue = providers.Singleton(Session)\n",
            "session-like object configured as DI Singleton",
        ),
    ],
)
def test_checks_still_reject_production_violations(
    checkout: Path, source: str, diagnostic: str
) -> None:
    (checkout / "backend/app/example.py").write_text(source, encoding="utf-8")
    result = run_checks(checkout)
    assert result.returncode != 0
    assert diagnostic in result.stdout


@pytest.mark.parametrize(
    "required_file",
    ["contracts.toml", "_verification_common.py", "verify_async_contracts.py"],
)
def test_missing_verification_inputs_fail(checkout: Path, required_file: str) -> None:
    (checkout / "backend/scripts/verification" / required_file).unlink()
    result = run_checks(checkout)
    assert result.returncode != 0
    assert Path(required_file).stem in result.stdout + result.stderr


def test_missing_production_source_root_fails(checkout: Path) -> None:
    shutil.rmtree(checkout / "backend/app")
    result = run_checks(checkout)
    assert result.returncode != 0
    assert "source roots do not exist" in result.stdout + result.stderr
