"""Bounded real-search probes for operational retrieval readiness."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.memory.application.contexts.records.context_service_ports import (
    ContextRetrievalCanaryPort,
)
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.operations.domain.entities.operational_retrieval_canary import (
    OperationalRetrievalCanaryResult,
    OperationalRetrievalCanarySnapshot,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextDomainError


class OperationalRetrievalCanaryService:
    """Execute FTS, vector, and hybrid searches through the normal Context path."""

    def __init__(
        self,
        context_service: ContextRetrievalCanaryPort,
        query: str,
        limit: int,
    ) -> None:
        """Create the bounded retrieval canary service.

        Args:
            context_service: Context search boundary used by production retrieval.
            query: Bounded canary query.
            limit: Result limit, which must exercise multi-candidate retrieval.
        """
        if limit < 3:
            raise ValueError("RETRIEVAL_CANARY_LIMIT_INVALID: limit must be at least 3")
        self._context_service = context_service
        self._query = query
        self._limit = limit

    async def snapshot(self) -> OperationalRetrievalCanarySnapshot:
        """Execute all required retrieval lanes sequentially.

        Returns:
            Per-lane real-search health through Context Pack construction.
        """
        fts = await self._probe(RagStrategy.FTS_ONLY)
        vector = await self._probe(RagStrategy.VECTOR_ONLY)
        hybrid = await self._probe(RagStrategy.HYBRID)
        return OperationalRetrievalCanarySnapshot(
            checked=True,
            query=self._query,
            limit=self._limit,
            fts=fts,
            vector=vector,
            hybrid=hybrid,
        )

    async def _probe(self, strategy: RagStrategy) -> OperationalRetrievalCanaryResult:
        """Execute one required retrieval lane and return a sanitized result.

        Args:
            strategy: Retrieval strategy exercised by this canary probe.

        Returns:
            Bounded per-lane result with success, result-count, warnings, and latency.
        """
        try:
            pack = await self._context_service.readiness_canary(
                query=self._query,
                strategy=strategy,
                limit=self._limit,
            )
        except (
            MemoryContextDomainError,
            SQLAlchemyError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            return OperationalRetrievalCanaryResult(
                strategy=strategy,
                ok=False,
                effective_strategy=None,
                match_count=0,
                context_pack_built=False,
                failure_code=f"{strategy.value.lower()}_search_failed",
            )
        context_pack_built = bool(pack.context_pack.strip())
        if pack.effective_strategy is not strategy:
            failure_code = f"{strategy.value.lower()}_strategy_fallback"
        elif not context_pack_built:
            failure_code = "context_pack_not_built"
        else:
            failure_code = None
        return OperationalRetrievalCanaryResult(
            strategy=strategy,
            ok=failure_code is None,
            effective_strategy=pack.effective_strategy,
            match_count=len(pack.matches),
            context_pack_built=context_pack_built,
            failure_code=failure_code,
            warnings=tuple(pack.warnings),
        )
