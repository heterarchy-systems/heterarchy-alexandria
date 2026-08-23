"""Golden-query integration tests for personal long-term-memory retrieval."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.domain.event_enum.context_enums import ContextKind, RagStrategy
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.shared.infrastructure.database import Database
from tests.memory.context_retrieval_kernel_test_provider import (
    TestContextRetrievalKernelProvider,
)
from tests.memory.context_seed import seed_context
from tests.memory.retrieval_quality_metrics import (
    GoldenRetrievalResult,
    mean_reciprocal_rank,
    recall_at_k,
)


@asynccontextmanager
async def _temporary_database(path: Path) -> AsyncIterator[Database]:
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        yield database
    finally:
        await database.shutdown()


def test_personal_memory_golden_queries_recall_expected_contexts(
    tmp_path: Path,
) -> None:
    """Representative Korean/technical queries should retrieve canonical notes."""

    async def scenario() -> tuple[GoldenRetrievalResult, ...]:
        async with (
            _temporary_database(tmp_path / "retrieval-quality.db") as database,
            database.session() as session,
        ):
            service = ContextService(
                retrieval_kernel_provider=TestContextRetrievalKernelProvider(),
                repository=SqlAlchemyContextRepository(session=session),
            )
            search_quality = await seed_context(
                session,
                kind=ContextKind.DECISION,
                title="검색 품질 개선 결정",
                summary="Golden query와 rank fusion을 검색 평가 기준으로 사용한다.",
                content=(
                    "# 검색 품질 개선 결정\n\n"
                    "검색 품질은 golden query, Recall@K, MRR로 회귀 평가한다."
                ),
            )
            mcp_host = await seed_context(
                session,
                kind=ContextKind.BUG_ROOT_CAUSE,
                title="MCP 421 Invalid Host 복구",
                summary="MCP 421 오류는 transport host 설정으로 복구한다.",
                content=(
                    "# MCP 421 Invalid Host 복구\n\n"
                    "SERVICE_MCP_TRANSPORT_HOST를 점검한다."
                ),
            )
            compact = await seed_context(
                session,
                kind=ContextKind.DECISION,
                title="Memory Compact CURRENT 생명주기",
                summary="Memory Compact CURRENT 노트의 최신성 정책.",
                content=(
                    "# Memory Compact CURRENT 생명주기\n\n"
                    "CURRENT compact는 refresh와 review를 거쳐 유지한다."
                ),
            )
            await seed_context(
                session,
                kind=ContextKind.RESEARCH,
                title="일반 운영 기록",
                summary="검색과 MCP와 Memory Compact를 언급하는 잡음 문서.",
                content="# 일반 운영 기록\n\n검색 MCP Memory Compact 점검.",
            )
            await session.commit()

            cases = (
                ("검색 품질 개선을 위해서 뭐가 있을까요?", search_quality.id),
                ("MCP 421 Invalid Host", mcp_host.id),
                ("Memory Compact CURRENT 생명주기", compact.id),
            )
            results: list[GoldenRetrievalResult] = []
            for query, expected_id in cases:
                pack = await service.search(
                    query=query,
                    strategy=RagStrategy.FTS_ONLY,
                    limit=3,
                )
                results.append(
                    GoldenRetrievalResult(
                        query=query,
                        expected_context_ids=(expected_id,),
                        retrieved_context_ids=tuple(
                            match.context.id for match in pack.matches
                        ),
                    )
                )
            return tuple(results)

    results = anyio.run(scenario)

    assert recall_at_k(results, 1) == 1.0
    assert mean_reciprocal_rank(results) == 1.0
