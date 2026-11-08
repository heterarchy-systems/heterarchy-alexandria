"""Installed-wheel probe for Alexandria's PyO3 GIL opt-out policy.

Run with an already-installed CPython 3.14t interpreter through
``cargo xtask gil-policy``. The probe deliberately builds into a unique target
directory and creates a temporary test-only wheel; it does not change release
packaging or claim free-threaded safety.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final


MODULE_NAME: Final = "heterarchy_alexandria_native"
PACKAGE_NAME: Final = "heterarchy-alexandria-native"
PACKAGE_VERSION: Final = "0.1.0"
RECEIPT_PREFIX: Final = "ALEXANDRIA_GIL_POLICY_RECEIPT "


class ProbeFailure(RuntimeError):
    """The installed-artifact GIL policy probe could not establish its claim."""


def validate_no_gil_overrides(
    environment: Mapping[str, str], original_argv: Sequence[str]
) -> None:
    """Reject startup controls that could force the interpreter's GIL mode."""
    if "PYTHON_GIL" in environment:
        raise ProbeFailure("PYTHON_GIL must be unset for the unforced probe")

    for index, argument in enumerate(original_argv):
        if argument == "-Xgil" or argument.startswith("-Xgil="):
            raise ProbeFailure("-Xgil startup overrides are forbidden for this probe")
        if argument == "-X" and index + 1 < len(original_argv):
            if original_argv[index + 1] == "gil" or original_argv[index + 1].startswith(
                "gil="
            ):
                raise ProbeFailure("-X gil startup overrides are forbidden for this probe")


def verify_override_guards() -> None:
    """Exercise both fail-closed branches without launching overridden Python."""
    cases = (
        ({"PYTHON_GIL": "1"}, ("python",)),
        ({}, ("python", "-Xgil")),
        ({}, ("python", "-X", "gil=enabled")),
    )
    for environment, arguments in cases:
        try:
            validate_no_gil_overrides(environment, arguments)
        except ProbeFailure:
            continue
        raise ProbeFailure("a simulated forced-GIL startup control was accepted")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeFailure(message)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    encoded = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}", size


def sha256_hex_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(contents: bytes) -> tuple[str, int]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest())
    return f"sha256={digest.rstrip(b'=').decode('ascii')}", len(contents)


def write_test_wheel(
    wheel_path: Path,
    extension_path: Path,
    extension_name: str,
    wheel_tag: str,
) -> None:
    """Wrap the exact built extension in a minimal, standards-shaped test wheel."""
    dist_info = f"heterarchy_alexandria_native-{PACKAGE_VERSION}.dist-info"
    metadata_path = f"{dist_info}/METADATA"
    wheel_metadata_path = f"{dist_info}/WHEEL"
    record_path = f"{dist_info}/RECORD"
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {PACKAGE_NAME}\n"
        f"Version: {PACKAGE_VERSION}\n\n"
    ).encode("utf-8")
    wheel_metadata = (
        "Wheel-Version: 1.0\n"
        "Generator: alexandria-gil-policy-probe\n"
        "Root-Is-Purelib: false\n"
        f"Tag: {wheel_tag}\n\n"
    ).encode("utf-8")

    extension_hash, extension_size = sha256_file(extension_path)
    metadata_hash, metadata_size = sha256_bytes(metadata)
    wheel_hash, wheel_size = sha256_bytes(wheel_metadata)
    rows = [
        (extension_name, extension_hash, str(extension_size)),
        (metadata_path, metadata_hash, str(metadata_size)),
        (wheel_metadata_path, wheel_hash, str(wheel_size)),
    ]
    record_buffer = io.StringIO(newline="")
    writer = csv.writer(record_buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    writer.writerow((record_path, "", ""))

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_STORED) as wheel:
        wheel.write(extension_path, extension_name)
        wheel.writestr(metadata_path, metadata)
        wheel.writestr(wheel_metadata_path, wheel_metadata)
        wheel.writestr(record_path, record_buffer.getvalue().encode("utf-8"))


def run_installed_import(
    venv_python: Path,
    outside_source_directory: Path,
    repository_root: Path,
    expected_soabi: str,
    expected_extension_suffix: str,
    expected_wheel_tag: str,
    expected_artifact_hash: str,
    environment: Mapping[str, str],
) -> dict[str, object]:
    child_code = f"""
import hashlib
import importlib
import json
import os
import pathlib
import sys
import sysconfig

def fail(message):
    raise SystemExit(message)

if "PYTHON_GIL" in os.environ:
    fail("installed-import child rejects PYTHON_GIL")
for index, argument in enumerate(sys.orig_argv):
    if argument == "-Xgil" or argument.startswith("-Xgil="):
        fail("installed-import child rejects -Xgil overrides")
    if argument == "-X" and index + 1 < len(sys.orig_argv):
        if sys.orig_argv[index + 1] == "gil" or sys.orig_argv[index + 1].startswith("gil="):
            fail("installed-import child rejects -X gil overrides")

if sys.implementation.name != "cpython" or tuple(sys.version_info[:2]) != (3, 14):
    fail("installed-import child requires CPython 3.14t")
if sysconfig.get_config_var("Py_GIL_DISABLED") != 1:
    fail("installed-import child did not detect Py_GIL_DISABLED=1")
if sysconfig.get_config_var("SOABI") != {expected_soabi!r}:
    fail("installed-import child SOABI differs from the build interpreter")
if sysconfig.get_config_var("EXT_SUFFIX") != {expected_extension_suffix!r}:
    fail("installed-import child extension suffix differs from the build interpreter")

gil_before_import = sys._is_gil_enabled()
if gil_before_import is not False:
    fail("GIL must be disabled before importing the native extension")
module = importlib.import_module({MODULE_NAME!r})
gil_after_import = sys._is_gil_enabled()
if gil_after_import is not True:
    fail("native extension import did not re-enable the GIL")
if module.compute_contract_version() != 1:
    fail("installed native extension returned an unexpected contract version")

extension_path = pathlib.Path(module.__file__).resolve()
venv_prefix = pathlib.Path(sys.prefix).resolve()
repository_root = pathlib.Path({str(repository_root)!r}).resolve()
if not extension_path.is_relative_to(venv_prefix):
    fail("native extension did not import from the isolated venv")
if extension_path.is_relative_to(repository_root):
    fail("native extension import resolved inside the repository")
if not extension_path.name.endswith({expected_extension_suffix!r}):
    fail("installed extension filename does not match the target ABI suffix")
digest = hashlib.sha256()
with extension_path.open("rb") as extension_file:
    while chunk := extension_file.read(1024 * 1024):
        digest.update(chunk)
extension_hash = digest.hexdigest()
if extension_hash != {expected_artifact_hash!r}:
    fail("installed extension bytes differ from the built artifact")

print({RECEIPT_PREFIX!r} + json.dumps({{
    "gil_enabled_before_import": gil_before_import,
    "gil_enabled_after_import": gil_after_import,
    "gil_disabled_build": sysconfig.get_config_var("Py_GIL_DISABLED"),
    "soabi": sysconfig.get_config_var("SOABI"),
    "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"),
    "wheel_tag": {expected_wheel_tag!r},
    "extension_path": str(extension_path),
    "venv_prefix": str(venv_prefix),
    "installed_artifact_sha256": extension_hash,
    "contract_version": module.compute_contract_version(),
}}, sort_keys=True))
"""
    command = [str(venv_python), "-I", "-c", child_code]
    completed = subprocess.run(
        command,
        cwd=outside_source_directory,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProbeFailure(
            "installed-import child failed\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    receipt_line = next(
        (
            line[len(RECEIPT_PREFIX) :]
            for line in completed.stdout.splitlines()
            if line.startswith(RECEIPT_PREFIX)
        ),
        None,
    )
    require(receipt_line is not None, "installed-import child omitted its receipt")
    receipt = json.loads(receipt_line)
    require(
        receipt["gil_enabled_before_import"] is False
        and receipt["gil_enabled_after_import"] is True,
        "installed-import child reported an unexpected GIL transition",
    )
    return receipt


def run_probe() -> tuple[dict[str, object], Path]:
    validate_no_gil_overrides(os.environ, sys.orig_argv)
    verify_override_guards()
    require(
        sys.implementation.name == "cpython" and tuple(sys.version_info[:2]) == (3, 14),
        "probe requires an already-installed CPython 3.14t interpreter",
    )
    gil_disabled = sysconfig.get_config_var("Py_GIL_DISABLED")
    require(gil_disabled == 1, "probe interpreter must report Py_GIL_DISABLED=1")
    gil_enabled_before_build = sys._is_gil_enabled()
    require(
        gil_enabled_before_build is False,
        "probe interpreter must start with the GIL disabled and no override",
    )

    soabi = sysconfig.get_config_var("SOABI")
    extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    require(isinstance(soabi, str) and "cpython-314t" in soabi, "unexpected CPython 3.14t SOABI")
    require(
        isinstance(extension_suffix, str) and "314t" in extension_suffix,
        "unexpected CPython 3.14t extension suffix",
    )
    platform = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    wheel_tag = f"cp314-cp314t-{platform}"
    distribution_tag = f"heterarchy_alexandria_native-{PACKAGE_VERSION}-{wheel_tag}"
    extension_name = f"{MODULE_NAME}{extension_suffix}"

    repository_root = Path(__file__).resolve().parents[2]
    cargo_manifest = repository_root / "native" / "Cargo.toml"
    require(cargo_manifest.is_file(), "native Cargo workspace manifest is missing")
    require(shutil.which("cargo") is not None, "cargo is required for the GIL policy probe")
    uv = shutil.which("uv")
    require(uv is not None, "uv is required for the installed-artifact GIL policy probe")
    temporary_root = os.environ.get("TMPDIR")
    require(temporary_root is not None, "TMPDIR must name the isolated probe temp root")
    require(Path(temporary_root).is_dir(), f"probe temp root does not exist: {temporary_root}")

    workspace = Path(
        tempfile.mkdtemp(
            prefix="alexandria-pyo3-gil-policy-",
            dir=temporary_root,
        )
    )
    try:
        cargo_target_directory = workspace / "cargo-target"
        build_environment = os.environ.copy()
        build_environment["CARGO_TARGET_DIR"] = str(cargo_target_directory)
        build_environment["PYO3_PYTHON"] = str(Path(sys.executable).resolve())
        build_environment["PYO3_BUILD_EXTENSION_MODULE"] = "1"
        subprocess.run(
            [
                "cargo",
                "build",
                "--locked",
                "--manifest-path",
                str(cargo_manifest),
                "-p",
                "heterarchy-alexandria-py",
            ],
            cwd=repository_root,
            env=build_environment,
            check=True,
        )

        if sys.platform == "darwin":
            artifact_suffix = ".dylib"
        elif sys.platform.startswith("linux"):
            artifact_suffix = ".so"
        else:
            raise ProbeFailure(f"unsupported probe platform: {sys.platform}")
        artifact = (
            cargo_target_directory
            / "debug"
            / f"lib{MODULE_NAME}{artifact_suffix}"
        )
        require(artifact.is_file(), f"built native artifact is missing: {artifact}")
        _, artifact_size = sha256_file(artifact)
        artifact_hash = sha256_hex_file(artifact)
        wheel_path = workspace / f"{distribution_tag}.whl"
        write_test_wheel(wheel_path, artifact, extension_name, wheel_tag)
        _, wheel_size = sha256_file(wheel_path)
        wheel_hash = sha256_hex_file(wheel_path)

        venv_directory = workspace / "venv"
        subprocess.run(
            [
                uv,
                "venv",
                "--offline",
                "--no-python-downloads",
                "--python",
                str(Path(sys.executable).resolve()),
                "--no-project",
                str(venv_directory),
            ],
            cwd=workspace,
            env=os.environ.copy(),
            check=True,
        )
        venv_python = venv_directory / "bin" / "python"
        require(venv_python.is_file(), f"temporary venv Python is missing: {venv_python}")
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--no-deps",
                "--offline",
                "--python",
                str(venv_python),
                str(wheel_path),
            ],
            cwd=workspace,
            env=os.environ.copy(),
            check=True,
        )
        outside_source_directory = workspace / "outside-source"
        outside_source_directory.mkdir()
        installed_receipt = run_installed_import(
            venv_python=venv_python,
            outside_source_directory=outside_source_directory,
            repository_root=repository_root,
            expected_soabi=soabi,
            expected_extension_suffix=extension_suffix,
            expected_wheel_tag=wheel_tag,
            expected_artifact_hash=artifact_hash,
            environment=os.environ,
        )
        return {
            "status": "PASS",
            "interpreter": str(Path(sys.executable).resolve()),
            "python_version": sys.version.split()[0],
            "py_gil_disabled": gil_disabled,
            "gil_enabled_before_native_import": gil_enabled_before_build,
            "gil_enabled_after_installed_native_import": installed_receipt[
                "gil_enabled_after_import"
            ],
            "abi": soabi,
            "extension_suffix": extension_suffix,
            "wheel_filename": wheel_path.name,
            "wheel_tag": wheel_tag,
            "probe_temp_root": temporary_root,
            "cargo_target_directory": str(cargo_target_directory),
            "built_artifact_sha256": artifact_hash,
            "built_artifact_size_bytes": artifact_size,
            "test_wheel_sha256": wheel_hash,
            "test_wheel_size_bytes": wheel_size,
            "installed_artifact_sha256": installed_receipt[
                "installed_artifact_sha256"
            ],
            "installed_extension_path": installed_receipt["extension_path"],
            "venv_prefix": installed_receipt["venv_prefix"],
            "isolated_venv_import": True,
            "negative_override_guards": {
                "PYTHON_GIL_rejected": True,
                "-Xgil_rejected_without_starting_overridden_python": True,
            },
            "native_import_receipt": installed_receipt,
        }, workspace
    except BaseException:
        print(f"GIL policy probe artifacts retained at {workspace}", file=sys.stderr)
        raise


def main() -> int:
    workspace: Path | None = None
    try:
        receipt, workspace = run_probe()
    except (ProbeFailure, OSError, subprocess.CalledProcessError) as error:
        print(f"gil-policy: FAIL — {error}", file=sys.stderr)
        return 1
    print(RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True), flush=True)
    if workspace is not None:
        try:
            shutil.rmtree(workspace)
        except OSError as error:
            print(f"gil-policy: temporary cleanup failed: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
