"""Behavior tests for retrieval primitives."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.application.retrieval.chunker import chunk_markdown
from app.memory.application.retrieval.embeddings.embedding_document import (
    EMBEDDING_DOCUMENT_INPUT_FORMAT,
    build_embedding_document_text,
)
from app.memory.application.retrieval.embeddings.fake_embedding_provider import (
    FakeEmbeddingProvider,
)
from app.memory.application.retrieval.planning.context_query_planning import (
    context_query_variants,
)
from app.memory.application.retrieval.ranking.context_ranking import (
    hybrid_candidate_limit,
    merge_hybrid_matches,
)
from app.memory.application.retrieval.ranking.vector_math import cosine_similarity
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

NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _retrieval_match(
    context_id: str,
    chunk_suffix: str,
    *,
    score: float,
    fts_score: float | None,
    vector_score: float | None,
) -> ContextSearchMatch:
    context = ContextRecord(
        id=context_id,
        kind=ContextKind.RESEARCH,
        title=f"Context {context_id}",
        summary="Retrieval quality fixture.",
        content="Search quality evidence.",
        content_format=ContextContentFormat.MARKDOWN,
        project="heterarchy-alexandria",
        scope=ContextScope.PROJECT,
        workspace_id="default",
        agent_id=None,
        user_id=None,
        session_id=None,
        visibility=ContextScope.PROJECT,
        source_agent="Hermes",
        source_type=ContextSourceType.AGENT,
        importance=ContextImportance.HIGH,
        tags=("retrieval-quality",),
        status=ContextStorageStatus.SAVED,
        quality_score=100,
        warnings=(),
        restore_prompt=None,
        context_metadata=ContextMetadataPayload(),
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=None,
        expires_at=None,
        archived_at=None,
        access_count=0,
        is_archived=False,
    )
    chunk = ContextChunkRecord(
        id=f"chunk-{context_id}-{chunk_suffix}",
        context_id=context_id,
        chunk_index=int(chunk_suffix),
        heading=f"Evidence {chunk_suffix}",
        content="Search quality evidence.",
        token_count=3,
        content_hash=f"hash-{context_id}-{chunk_suffix}",
        chunk_metadata=ContextMetadataPayload(),
        created_at=NOW,
    )
    return ContextSearchMatch(
        context=context,
        chunk=chunk,
        score=score,
        fts_score=fts_score,
        vector_score=vector_score,
        why_retrieved="Single retrieval lane.",
    )


def test_markdown_chunker_keeps_heading_metadata_and_hashes() -> None:
    """Markdown chunks should retain heading context for recall explanations."""
    chunks = chunk_markdown(
        title="Decision log",
        content="""# Decision log

## Summary
Use local embeddings.

## Evidence
FastEmbed works locally.
""",
    )

    assert [chunk.heading for chunk in chunks] == [
        "Decision log",
        "Summary",
        "Evidence",
    ]
    assert [chunk.token_count for chunk in chunks] == [2, 4, 4]
    assert [chunk.content_hash for chunk in chunks] == [
        "b3297da392cbbb0893201b7cdc3121e35f2b34190868b94ff1d221ec394acec7",
        "6933f5bf2cb64cf2dfb59560a04dd92c07fcd95d63fa6031f9d69eb34aff029e",
        "9985ad61dbafad3c91f809680f1c42896a60162d8991419d2c9fcad8987f78c3",
    ]
    assert chunks[1].metadata == {"title": "Decision log", "heading": "Summary"}


def test_markdown_chunker_bounds_and_overlaps_large_sections() -> None:
    """Large note sections should stay bounded while preserving boundary context."""
    content = "# 검색 품질\n\n" + " ".join(f"검색토큰-{index}" for index in range(600))

    chunks = chunk_markdown(title="검색 품질", content=content)

    assert len(chunks) > 2
    assert all(len(chunk.content) <= 1400 for chunk in chunks)
    first_tail = set(chunks[0].content.split()[-15:])
    second_head = set(chunks[1].content.split()[:30])
    assert len(first_tail & second_head) >= 5


def test_markdown_chunker_bounds_single_unbroken_paragraph() -> None:
    """A paragraph without whitespace must not exceed the configured chunk bound."""
    chunks = chunk_markdown(
        title="Unbroken",
        content="x" * 3200,
    )

    assert [len(chunk.content) for chunk in chunks] == [1400, 1400, 400]


def test_fake_embedding_provider_is_deterministic_without_model_downloads() -> None:
    """Tests should embed text without touching external model caches."""
    provider = FakeEmbeddingProvider()

    first = provider.embed_query("context recall")
    second = provider.embed_documents(["context recall"])[0]

    assert first == second
    assert len(first) == provider.dimensions


def test_embedding_document_text_includes_title_and_heading() -> None:
    """Document vectors should encode structural metadata with chunk content."""
    text = build_embedding_document_text(
        content="검색 품질은 rank fusion으로 평가한다.",
        title="Alexandria 검색",
        heading="Hybrid ranking",
    )

    assert text == (
        "Title: Alexandria 검색\n"
        "Heading: Hybrid ranking\n\n"
        "검색 품질은 rank fusion으로 평가한다."
    )
    fingerprint = FakeEmbeddingProvider().fingerprint()
    assert fingerprint.document_input_format == EMBEDDING_DOCUMENT_INPUT_FORMAT
    assert (
        fingerprint.identity_payload()["document_input_format"]
        == EMBEDDING_DOCUMENT_INPUT_FORMAT
    )


def test_cosine_similarity_package_contract_handles_vector_edges() -> None:
    """The ranking package should expose deterministic cosine similarity behavior."""
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0


def test_hybrid_candidate_limit_overfetches_before_final_ranking() -> None:
    """Hybrid recall should gather enough candidates for cross-lane fusion."""
    assert hybrid_candidate_limit(1) == 6
    assert hybrid_candidate_limit(5) == 30
    assert hybrid_candidate_limit(20) == 50


def test_context_query_variants_include_focused_korean_topic_terms() -> None:
    """Natural Korean questions should retain a focused lexical fallback."""
    variants = context_query_variants("검색 품질 개선을 위해서 뭐가 있을까요?")

    assert variants[0] == "검색 품질 개선을 위해서 뭐가 있을까요?"
    assert "검색 품질" in variants
    assert len(variants) <= 16


def test_hybrid_rank_fusion_combines_context_evidence_across_chunks() -> None:
    """A context found by both lanes should retain both signals across chunks."""
    fts_match = _retrieval_match(
        "dual-source",
        "1",
        score=0.000003,
        fts_score=0.000003,
        vector_score=None,
    )
    vector_match = _retrieval_match(
        "dual-source",
        "2",
        score=0.91,
        fts_score=None,
        vector_score=0.91,
    )

    ranked = merge_hybrid_matches(
        fts_matches=[fts_match],
        vector_matches=[vector_match],
        limit=5,
    )

    assert len(ranked) == 1
    assert ranked[0].fts_score == fts_match.fts_score
    assert ranked[0].vector_score == vector_match.vector_score
    assert "reciprocal rank fusion" in ranked[0].why_retrieved


def test_hybrid_rank_fusion_does_not_let_vector_scale_erase_fts_rank() -> None:
    """Rank fusion should compare lane positions instead of raw score magnitude."""
    lexical = _retrieval_match(
        "lexical",
        "1",
        score=0.000004,
        fts_score=0.000004,
        vector_score=None,
    )
    semantic = _retrieval_match(
        "semantic",
        "1",
        score=0.99,
        fts_score=None,
        vector_score=0.99,
    )

    ranked = merge_hybrid_matches(
        fts_matches=[lexical],
        vector_matches=[semantic],
        limit=2,
    )

    assert [match.context.id for match in ranked] == ["lexical", "semantic"]
