"""Contract tests for the native Context retrieval-kernel adapter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextRecord,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import (
    ContextContentFormat,
    ContextImportance,
    ContextKind,
    ContextScope,
    ContextSourceType,
    ContextStorageStatus,
)
from app.memory.domain.types.context_payload_types import ContextMetadataPayload
from app.memory.infrastructure.providers.native_context_retrieval_kernel_provider import (
    NativeBestRow,
    NativeContextRetrievalKernelProvider,
    NativeFusionRow,
    NativeFusionTraceResult,
)

_NOW = datetime(2026, 8, 22, tzinfo=UTC)


class _FakeNativeModule:
    def __init__(
        self,
        fusion_rows: list[NativeFusionRow] | None = None,
        best_rows: list[NativeBestRow] | None = None,
        candidate_limit: int = 30,
        fusion_trace_result: NativeFusionTraceResult | None = None,
    ) -> None:
        self.fusion_rows = list(fusion_rows or [])
        self.best_rows = list(best_rows or [])
        self.candidate_limit = candidate_limit
        self.fusion_trace_result = fusion_trace_result or (
            [],
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        )
        self.fusion_calls: list[tuple[list[str], list[str], int]] = []
        self.fusion_trace_calls: list[tuple[list[str], list[str], int]] = []
        self.best_calls: list[tuple[list[tuple[str, float]], int]] = []
        self.candidate_limit_calls: list[int] = []

    def compute_contract_version(self) -> int:
        return 1

    def retrieval_hybrid_candidate_limit(self, limit: int) -> int:
        self.candidate_limit_calls.append(limit)
        return self.candidate_limit

    def retrieval_merge_hybrid_indices(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> list[NativeFusionRow]:
        self.fusion_calls.append((fts_context_ids, vector_context_ids, limit))
        return list(self.fusion_rows)

    def retrieval_merge_hybrid_indices_with_trace(
        self,
        fts_context_ids: list[str],
        vector_context_ids: list[str],
        limit: int,
    ) -> NativeFusionTraceResult:
        self.fusion_trace_calls.append((fts_context_ids, vector_context_ids, limit))
        rows, trace = self.fusion_trace_result
        return list(rows), trace

    def retrieval_rank_best_indices(
        self,
        candidates: list[tuple[str, float]],
        limit: int,
    ) -> list[NativeBestRow]:
        self.best_calls.append((candidates, limit))
        return list(self.best_rows)


def _match(
    context_id: str,
    suffix: int,
    *,
    score: float,
    fts_score: float | None,
    vector_score: float | None,
) -> ContextSearchMatch:
    context = ContextRecord(
        id=context_id,
        kind=ContextKind.RESEARCH,
        title=context_id,
        summary="native adapter fixture",
        content="native adapter fixture",
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id="default",
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="test",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=(),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata=ContextMetadataPayload(),
        created_at=_NOW,
        updated_at=_NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{context_id}-{suffix}",
        context_id=context_id,
        chunk_index=suffix,
        heading=None,
        content="native adapter fixture",
        token_count=3,
        content_hash=f"hash-{context_id}-{suffix}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=_NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=fts_score,
        vector_score=vector_score,
        why_retrieved=("fts lane" if fts_score is not None else "vector lane"),
    )


def test_native_adapter_delegates_candidate_limit() -> None:
    native = _FakeNativeModule(candidate_limit=30)
    provider = NativeContextRetrievalKernelProvider(native)

    assert provider.hybrid_candidate_limit(5) == 30
    assert native.candidate_limit_calls == [5]


def test_native_adapter_maps_compact_fusion_rows_without_heavy_dto_crossing() -> None:
    fts = [
        _match("dual", 1, score=0.8, fts_score=0.8, vector_score=None),
        _match("lexical", 2, score=0.7, fts_score=0.7, vector_score=None),
    ]
    vector = [
        _match("semantic", 3, score=0.99, fts_score=None, vector_score=0.99),
        _match("dual", 4, score=0.95, fts_score=None, vector_score=0.95),
    ]
    native = _FakeNativeModule(
        fusion_rows=[
            ("vector", 0, None, 0, 0.01655737704918033),
            ("vector", 1, 0, 1, 0.01629032258064516),
            ("fts", 1, 1, None, 0.016129032258064516),
        ]
    )

    actual = NativeContextRetrievalKernelProvider(native).merge(fts, vector, limit=3)

    assert native.fusion_calls == [(["dual", "lexical"], ["semantic", "dual"], 3)]
    assert [match.context.id for match in actual] == ["semantic", "dual", "lexical"]
    assert actual[0].chunk.id == vector[0].chunk.id
    assert actual[1].chunk.id == vector[1].chunk.id
    assert actual[1].fts_score == fts[0].fts_score
    assert actual[1].vector_score == vector[1].vector_score
    assert "best-lane reciprocal-rank fusion" in actual[1].why_retrieved


def test_native_adapter_maps_trace_rows_and_validates_native_counters() -> None:
    fts = [
        _match("dual", 1, score=0.8, fts_score=0.8, vector_score=None),
        _match("lexical", 2, score=0.7, fts_score=0.7, vector_score=None),
    ]
    vector = [
        _match("semantic", 3, score=0.99, fts_score=None, vector_score=0.99),
        _match("dual", 4, score=0.95, fts_score=None, vector_score=0.95),
    ]
    native = _FakeNativeModule(
        fusion_trace_result=(
            [
                ("vector", 0, None, 0, 0.01655737704918033),
                ("vector", 1, 0, 1, 0.01629032258064516),
            ],
            (2, 2, 2, 2, 0, 0, 3, 1, 2, 0, 2),
        )
    )

    result = NativeContextRetrievalKernelProvider(native).merge_with_trace(
        fts, vector, limit=2
    )

    assert [match.context.id for match in result.matches] == ["semantic", "dual"]
    assert result.trace.fused_candidate_count == 3
    assert result.trace.cross_lane_count == 1
    assert result.trace.returned_count == 2
    assert native.fusion_trace_calls == [(["dual", "lexical"], ["semantic", "dual"], 2)]


@pytest.mark.parametrize(
    "trace_row",
    [
        (1, 2, 1, 2, 0, 0, 3, 0, 1, 0, 1),
        (2, 2, 2, 2, 0, 0, 5, 0, 1, 0, 1),
        (2, 2, 2, 2, 0, 0, 3, 3, 1, 0, 1),
        (2, 2, 2, 2, 0, 0, 3, 1, 2, 0, 2),
    ],
)
def test_native_adapter_fails_closed_on_invalid_trace_output(
    trace_row: tuple[int, int, int, int, int, int, int, int, int, int, int],
) -> None:
    fts = [
        _match("a", 1, score=0.8, fts_score=0.8, vector_score=None),
        _match("b", 2, score=0.7, fts_score=0.7, vector_score=None),
    ]
    vector = [
        _match("c", 3, score=0.9, fts_score=None, vector_score=0.9),
        _match("a", 4, score=0.85, fts_score=None, vector_score=0.85),
    ]
    native = _FakeNativeModule(
        fusion_trace_result=(
            [
                ("vector", 0, None, 0, 0.01655737704918033),
            ],
            trace_row,
        )
    )

    with pytest.raises(ValueError, match="NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR"):
        NativeContextRetrievalKernelProvider(native).merge_with_trace(
            fts, vector, limit=1
        )


def test_native_adapter_maps_best_per_context_indices() -> None:
    matches = [
        _match("a", 1, score=0.4, fts_score=0.4, vector_score=None),
        _match("b", 1, score=0.9, fts_score=0.9, vector_score=None),
        _match("a", 2, score=0.8, fts_score=0.8, vector_score=None),
    ]
    native = _FakeNativeModule(best_rows=[(1, 0.9), (2, 0.8)])

    actual = NativeContextRetrievalKernelProvider(native).rank_best(matches, limit=2)

    assert native.best_calls == [([("a", 0.4), ("b", 0.9), ("a", 0.8)], 2)]
    assert actual == [matches[1], matches[2]]


@pytest.mark.parametrize(
    "fusion_row",
    [
        ("unknown", 0, None, None, 0.1),
        ("fts", 9, None, None, 0.1),
        ("vector", 0, None, 9, 0.1),
        ("fts", 0, 0, None, float("nan")),
    ],
)
def test_native_adapter_fails_closed_on_invalid_fusion_output(
    fusion_row: NativeFusionRow,
) -> None:
    fts = [_match("fts", 1, score=0.8, fts_score=0.8, vector_score=None)]
    vector = [_match("vector", 2, score=0.9, fts_score=None, vector_score=0.9)]

    with pytest.raises(ValueError, match="NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR"):
        NativeContextRetrievalKernelProvider(
            _FakeNativeModule(fusion_rows=[fusion_row])
        ).merge(fts, vector, limit=1)


@pytest.mark.parametrize(
    "best_rows",
    [
        [(9, 0.8)],
        [(0, float("nan"))],
        [(0, 0.8), (0, 0.8)],
        [(0, 0.7)],
    ],
)
def test_native_adapter_fails_closed_on_invalid_best_output(
    best_rows: list[NativeBestRow],
) -> None:
    matches = [_match("a", 1, score=0.8, fts_score=0.8, vector_score=None)]

    with pytest.raises(ValueError, match="NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR"):
        NativeContextRetrievalKernelProvider(
            _FakeNativeModule(best_rows=best_rows)
        ).rank_best(matches, limit=1)


def test_native_adapter_rejects_candidate_limit_below_requested_limit() -> None:
    provider = NativeContextRetrievalKernelProvider(
        _FakeNativeModule(candidate_limit=4)
    )

    with pytest.raises(ValueError, match="NATIVE_RETRIEVAL_KERNEL_OUTPUT_ERROR"):
        provider.hybrid_candidate_limit(5)
