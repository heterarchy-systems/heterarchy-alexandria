"""Shared native Markdown chunk adapter contracts."""

from __future__ import annotations

import json

import pytest
from app.shared.search.native_markdown_text_chunking import NativeMarkdownTextChunker


class _FakeNativeChunkingModule:
    def compute_contract_version(self) -> int:
        return 1

    def chunk_markdown_batch_json(self, payload: bytes) -> bytes:
        request = json.loads(payload)
        assert request["documents"][0]["title"] == "Fallback"
        return json.dumps(
            {
                "contract_version": 1,
                "chunking_version": 1,
                "policy": {"max_chars": 1400, "overlap_chars": 160},
                "results": [
                    {
                        "status": "success",
                        "document_id": "shared-markdown-chunk",
                        "relative_path": "Shared/Search.md",
                        "chunks": [
                            {
                                "chunk_index": 0,
                                "heading": "Fallback",
                                "heading_path": [],
                                "content": "Fallback",
                                "source_kind": "title_fallback",
                                "source_range": {
                                    "char_start": 0,
                                    "char_end": 8,
                                    "byte_start": 0,
                                    "byte_end": 8,
                                },
                            }
                        ],
                    }
                ],
            }
        ).encode()


def test_native_chunker_maps_strict_result_to_shared_dto() -> None:
    chunks = NativeMarkdownTextChunker(_FakeNativeChunkingModule()).split(
        title="Fallback",
        content="",
        max_chars=1400,
        overlap_chars=160,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].heading == "Fallback"
    assert chunks[0].content == "Fallback"


def test_native_chunker_fails_closed_on_contract_drift() -> None:
    class _BrokenModule(_FakeNativeChunkingModule):
        def chunk_markdown_batch_json(self, payload: bytes) -> bytes:
            del payload
            return b'{"contract_version":1,"chunking_version":2,"results":[]}'

    with pytest.raises(ValueError, match="NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR"):
        NativeMarkdownTextChunker(_BrokenModule()).split(
            title="Fallback",
            content="",
            max_chars=1400,
            overlap_chars=160,
        )
