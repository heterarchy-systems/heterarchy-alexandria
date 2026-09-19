"""Prove that linked Rust artifacts cannot initialize as Python extensions."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from importlib.machinery import ExtensionFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Protocol, cast

MODULE_NAME = "heterarchy_alexandria_native"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class NativeModule(Protocol):
    def compute_contract_version(self) -> int: ...


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("--mode", choices=("linked", "extension"), required=True)
    args = parser.parse_args()
    if args.mode == "linked":
        environment = os.environ.copy()
        environment.pop("PYO3_BUILD_EXTENSION_MODULE", None)
        environment["PYO3_PYTHON"] = sys.executable
        subprocess.run(
            [
                "cargo",
                "build",
                "--manifest-path",
                "native/Cargo.toml",
                "-p",
                "heterarchy-alexandria-py",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=True,
        )
    library = args.library.resolve(strict=True)
    specification = spec_from_file_location(
        MODULE_NAME, library, loader=ExtensionFileLoader(MODULE_NAME, str(library))
    )
    if specification is None or specification.loader is None:
        raise AssertionError("native import specification is missing")
    try:
        module = module_from_spec(specification)
        specification.loader.exec_module(module)
    except ImportError as error:
        if args.mode != "linked" or f"PyInit_{MODULE_NAME}" not in str(error):
            raise
        print("native-import-mode: PASS linked artifact has no Python entry point")
        return
    if args.mode != "extension":
        raise AssertionError(
            "linked artifact unexpectedly exposes a Python entry point"
        )
    if cast(NativeModule, module).compute_contract_version() != 1:
        raise AssertionError("native extension contract version drift")
    print("native-import-mode: PASS extension artifact initializes successfully")


if __name__ == "__main__":
    main()
