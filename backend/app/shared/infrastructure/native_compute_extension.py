"""Fail-closed loader for the heterarchy-alexandria native compute extension."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from importlib.machinery import ExtensionFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Protocol, cast

_NATIVE_MODULE_NAME = "heterarchy_alexandria_native"
_NATIVE_COMPUTE_CONTRACT_VERSION = 1
_NATIVE_LIBRARY_ENV = "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY"
_NATIVE_LIBRARY_SOURCE_ATTRIBUTE = "__heterarchy_alexandria_native_library_source__"


# protocol-contract: structural-seam
class NativeComputeContractModule(Protocol):
    """Minimal shared contract exposed by every compatible native module."""

    def compute_contract_version(self) -> int:
        """Return the coarse Python/Rust compute contract version.

        Returns:
            Native compute contract version.
        """


def load_native_compute_module() -> NativeComputeContractModule:
    """Load and validate the required native compute extension.

    Returns:
        Native module exposing the current compute contract.

    Raises:
        RuntimeError: If the extension is missing or contract-incompatible.
    """
    configured_library = os.environ.get(_NATIVE_LIBRARY_ENV)
    try:
        module = (
            _load_native_compute_library(Path(configured_library))
            if configured_library
            else cast(NativeComputeContractModule, import_module(_NATIVE_MODULE_NAME))
        )
        contract_version = module.compute_contract_version()
    except (ImportError, OSError, AttributeError) as exc:
        raise RuntimeError(
            "NATIVE_COMPUTE_UNAVAILABLE: required native extension is not installed"
        ) from exc
    if contract_version != _NATIVE_COMPUTE_CONTRACT_VERSION:
        raise RuntimeError(
            "NATIVE_COMPUTE_CONTRACT_ERROR: expected compute contract "
            f"{_NATIVE_COMPUTE_CONTRACT_VERSION}, found {contract_version}"
        )
    return module


def _load_native_compute_library(path: Path) -> NativeComputeContractModule:
    """Load the configured Rust extension library without a Python wheel install.

    Args:
        path: Explicit native extension library path supplied by the test/CI harness.

    Returns:
        Loaded native compute module.

    Raises:
        ImportError: If the configured library cannot be loaded as the native module.
    """
    library_path = path.expanduser().resolve()
    if not library_path.is_file():
        raise ImportError(
            f"configured native compute library is missing: {library_path}"
        )
    existing = sys.modules.get(_NATIVE_MODULE_NAME)
    if existing is not None:
        existing_path = Path(str(existing.__dict__.get("__file__", ""))).resolve()
        configured_source = existing.__dict__.get(_NATIVE_LIBRARY_SOURCE_ATTRIBUTE)
        if existing_path != library_path and configured_source != str(library_path):
            raise ImportError(
                "configured native compute library conflicts with the already loaded module"
            )
        return cast(NativeComputeContractModule, existing)
    loader = ExtensionFileLoader(_NATIVE_MODULE_NAME, str(library_path))
    specification = spec_from_file_location(
        _NATIVE_MODULE_NAME,
        library_path,
        loader=loader,
    )
    if specification is None or specification.loader is None:
        raise ImportError(
            f"unable to create native compute module spec: {library_path}"
        )
    module = module_from_spec(specification)
    module.__dict__[_NATIVE_LIBRARY_SOURCE_ATTRIBUTE] = str(library_path)
    sys.modules[_NATIVE_MODULE_NAME] = module
    try:
        specification.loader.exec_module(module)
    except (ImportError, OSError):
        sys.modules.pop(_NATIVE_MODULE_NAME, None)
        raise
    return cast(NativeComputeContractModule, module)
