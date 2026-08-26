"""Read models for bounded end-to-end retrieval readiness canaries."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory.domain.event_enum.context_enums import RagStrategy


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalRetrievalCanaryResult:
    """One real retrieval-lane probe executed through the Context application path."""

    strategy: RagStrategy
    ok: bool
    effective_strategy: RagStrategy | None
    match_count: int
    context_pack_built: bool
    failure_code: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalRetrievalCanarySnapshot:
    """Bounded FTS, vector, and hybrid retrieval path health."""

    checked: bool
    query: str
    limit: int
    fts: OperationalRetrievalCanaryResult
    vector: OperationalRetrievalCanaryResult
    hybrid: OperationalRetrievalCanaryResult

    @property
    def healthy(self) -> bool:
        """Return whether every required retrieval lane completed successfully.

        Returns:
            True when FTS, vector, and hybrid probes all succeeded.
        """
        return self.fts.ok and self.vector.ok and self.hybrid.ok


def unchecked_retrieval_canary_snapshot() -> OperationalRetrievalCanarySnapshot:
    """Return a neutral retrieval-canary snapshot for legacy boundaries.

    Returns:
        Unchecked snapshot containing neutral results for every required lane.
    """
    return OperationalRetrievalCanarySnapshot(
        checked=False,
        query="",
        limit=3,
        fts=_unchecked_result(RagStrategy.FTS_ONLY),
        vector=_unchecked_result(RagStrategy.VECTOR_ONLY),
        hybrid=_unchecked_result(RagStrategy.HYBRID),
    )


def _unchecked_result(strategy: RagStrategy) -> OperationalRetrievalCanaryResult:
    """Return one neutral canary result that has not been executed.

    Args:
        strategy: Retrieval strategy represented by the neutral result.

    Returns:
        Unchecked result for the requested retrieval strategy.
    """
    return OperationalRetrievalCanaryResult(
        strategy=strategy,
        ok=False,
        effective_strategy=None,
        match_count=0,
        context_pack_built=False,
        failure_code="not_checked",
    )
