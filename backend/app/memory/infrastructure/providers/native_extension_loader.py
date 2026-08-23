"""Fail-closed loader for the heterarchy-alexandria native extension."""

from __future__ import annotations

from typing import cast

from app.memory.infrastructure.providers.native_context_retrieval_kernel_provider import (
    NativeContextRetrievalKernelProvider,
    NativeRetrievalKernelModule,
)
from app.shared.infrastructure.native_compute_extension import (
    load_native_compute_module,
)


def load_native_retrieval_kernel_module() -> NativeRetrievalKernelModule:
    """Load the shared native module as the retrieval-kernel feature surface.

    Returns:
        Native extension surface required by deterministic retrieval ranking.
    """
    return cast(NativeRetrievalKernelModule, load_native_compute_module())


def create_native_context_retrieval_kernel_provider() -> (
    NativeContextRetrievalKernelProvider
):
    """Create the fail-closed production adapter over the validated native module.

    Returns:
        Native retrieval-kernel provider backed by the validated extension.
    """
    return NativeContextRetrievalKernelProvider(load_native_retrieval_kernel_module())
