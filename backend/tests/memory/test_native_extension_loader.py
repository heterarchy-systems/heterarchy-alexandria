"""Fail-closed native extension loader contracts."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest
from app.memory.infrastructure.providers.native_extension_loader import (
    create_native_context_retrieval_kernel_provider,
    load_native_retrieval_kernel_module,
)


class _CompatibleModule(ModuleType):
    def compute_contract_version(self) -> int:
        return 1

    def retrieval_hybrid_candidate_limit(self, limit: int) -> int:
        return limit

    def retrieval_merge_hybrid_indices(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> list[tuple[str, int, int | None, int | None, float]]:
        del fts_context_ids, vector_context_ids, limit
        return []

    def retrieval_rank_best_indices(
        self,
        candidates: list[tuple[str, float]],
        limit: int,
    ) -> list[tuple[int, float]]:
        del candidates, limit
        return []


class _IncompatibleModule(_CompatibleModule):
    def compute_contract_version(self) -> int:
        return 2


def test_loader_accepts_the_exact_compute_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY", raising=False)
    module = _CompatibleModule("heterarchy_alexandria_native")
    monkeypatch.setitem(sys.modules, "heterarchy_alexandria_native", module)

    loaded = load_native_retrieval_kernel_module()
    provider = create_native_context_retrieval_kernel_provider()

    assert loaded is module
    assert provider.native_module is module


def test_loader_rejects_incompatible_compute_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY", raising=False)
    module = _IncompatibleModule("heterarchy_alexandria_native")
    monkeypatch.setitem(sys.modules, "heterarchy_alexandria_native", module)

    with pytest.raises(RuntimeError, match="NATIVE_COMPUTE_CONTRACT_ERROR"):
        load_native_retrieval_kernel_module()


def test_loader_has_no_python_fallback_when_extension_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY", raising=False)
    monkeypatch.delitem(sys.modules, "heterarchy_alexandria_native", raising=False)

    with pytest.raises(RuntimeError, match="NATIVE_COMPUTE_UNAVAILABLE"):
        load_native_retrieval_kernel_module()
