"""Focused readiness contracts for runtime provenance and real retrieval canaries."""

from __future__ import annotations

from collections.abc import Callable

import anyio

import pytest

from app.memory.application.contexts.records.context_service_ports import (
    ContextRetrievalCanaryPort,
)
from app.memory.domain.entities.context_read_models import ContextPack
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.operations.application.readiness import (
    operational_runtime_provenance_service as provenance_module,
)
from app.operations.application.readiness.operational_retrieval_canary_service import (
    OperationalRetrievalCanaryService,
)
from app.operations.application.readiness.operational_runtime_provenance_service import (
    OperationalRuntimeProvenanceService,
)
from app.platform.config.app_config import AppConfig


class _NativeProvenance:
    """Deterministic native provenance fake for runtime readiness tests."""

    def __init__(self, revision: str) -> None:
        self._revision = revision

    def compute_contract_version(self) -> int:
        return 1

    def native_package_version(self) -> str:
        return "0.1.0"

    def native_git_revision(self) -> str:
        return self._revision

    def native_build_profile(self) -> str:
        return "release"

    def feature_authority_schema_version(self) -> int:
        return 1


class _CanaryContextService(ContextRetrievalCanaryPort):
    """Record retrieval canary calls and return deterministic Context Packs."""

    def __init__(
        self,
        effective_strategy: Callable[[RagStrategy], RagStrategy] | None = None,
        context_pack: str = "# Alexandria Context Pack\n",
    ) -> None:
        self.calls: list[tuple[str, RagStrategy, int]] = []
        self._effective_strategy = effective_strategy or (lambda strategy: strategy)
        self._context_pack = context_pack

    async def readiness_canary(
        self,
        query: str,
        strategy: RagStrategy,
        limit: int,
    ) -> ContextPack:
        self.calls.append((query, strategy, limit))
        return ContextPack(
            query=query,
            strategy=strategy,
            effective_strategy=self._effective_strategy(strategy),
            warnings=(),
            recall_scopes=(),
            matches=(),
            context_pack=self._context_pack,
        )


def _config(
    environment: str,
    runtime_revision: str | None,
    expected_revision: str | None,
) -> AppConfig:
    """Build isolated typed application settings for one provenance scenario."""
    return AppConfig(
        _env_file=None,
        app_env=environment,
        runtime_revision=runtime_revision,
        runtime_expected_revision=expected_revision,
    )


def test_runtime_provenance_verifies_matching_runtime_and_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching deployment, image, and native revisions are fully verified."""
    monkeypatch.setattr(
        provenance_module,
        "load_native_runtime_provenance_module",
        lambda: _NativeProvenance("abc123"),
    )

    snapshot = OperationalRuntimeProvenanceService(
        _config("prod", "abc123", "abc123")
    ).snapshot()

    assert snapshot.checked is True
    assert snapshot.verified is True
    assert snapshot.native_aligned is True
    assert snapshot.warnings == ()


def test_runtime_provenance_detects_image_revision_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale application image must be classified as runtime drift."""
    monkeypatch.setattr(
        provenance_module,
        "load_native_runtime_provenance_module",
        lambda: _NativeProvenance("old-revision"),
    )

    snapshot = OperationalRuntimeProvenanceService(
        _config("prod", "old-revision", "new-revision")
    ).snapshot()

    assert snapshot.verified is False
    assert snapshot.drift_detected is True
    assert "runtime_revision_mismatch" in snapshot.warnings


def test_local_runtime_without_expected_revision_is_explicitly_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local development remains usable while provenance stays visibly unverified."""
    monkeypatch.setattr(
        provenance_module,
        "load_native_runtime_provenance_module",
        lambda: _NativeProvenance("local-revision"),
    )

    snapshot = OperationalRuntimeProvenanceService(
        _config("local", "local-revision", None)
    ).snapshot()

    assert snapshot.verified is False
    assert snapshot.drift_detected is False
    assert snapshot.warnings == ("runtime_provenance_unverified",)


def test_retrieval_canary_executes_three_real_lanes_with_multi_result_limit() -> None:
    """Readiness exercises FTS, vector, and hybrid through Context Pack construction."""

    async def scenario() -> None:
        context_service = _CanaryContextService()
        service = OperationalRetrievalCanaryService(
            context_service=context_service,
            query="Alexandria readiness canary",
            limit=3,
        )

        snapshot = await service.snapshot()

        assert snapshot.healthy is True
        assert [strategy for _, strategy, _ in context_service.calls] == [
            RagStrategy.FTS_ONLY,
            RagStrategy.VECTOR_ONLY,
            RagStrategy.HYBRID,
        ]
        assert {limit for _, _, limit in context_service.calls} == {3}

    anyio.run(scenario)


def test_retrieval_canary_rejects_hybrid_fallback() -> None:
    """A requested HYBRID path that falls back must not report healthy."""

    async def scenario() -> None:
        context_service = _CanaryContextService(
            effective_strategy=lambda strategy: (
                RagStrategy.FTS_ONLY if strategy is RagStrategy.HYBRID else strategy
            )
        )
        service = OperationalRetrievalCanaryService(
            context_service=context_service,
            query="Alexandria readiness canary",
            limit=3,
        )

        snapshot = await service.snapshot()

        assert snapshot.healthy is False
        assert snapshot.hybrid.ok is False
        assert snapshot.hybrid.failure_code == "hybrid_strategy_fallback"

    anyio.run(scenario)
