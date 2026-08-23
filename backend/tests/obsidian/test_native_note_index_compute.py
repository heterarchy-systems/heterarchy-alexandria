"""Contracts for the coarse native Obsidian note-index adapter."""

from __future__ import annotations

from typing import cast

import pytest
from app.obsidian.infrastructure.markdown.native_note_index_compute import (
    NativeDocumentIndexComputeModule,
    NativeNoteIndexComputeProvider,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue


class _FakeNativeModule:
    def __init__(self) -> None:
        self.request: JSONValue | None = None
        self.content_hash = "a" * 64

    def compute_contract_version(self) -> int:
        return 1

    def compute_document_index_batch_json(self, payload: bytes) -> bytes:
        self.request = loads_json(payload)
        response: JSONValue = {
            "contract_version": 1,
            "analysis_version": 1,
            "chunking_version": 1,
            "hashing_version": 1,
            "results": [
                {
                    "status": "success",
                    "document_id": "obsidian-note-index-document",
                    "relative_path": "Projects/Example.md",
                    "analysis": {
                        "analysis_version": 1,
                        "frontmatter": [
                            {
                                "key": "title",
                                "value": {"kind": "string", "value": "Canonical Title"},
                            },
                            {
                                "key": "priority",
                                "value": {"kind": "integer", "value": "7"},
                            },
                        ],
                        "body": "# Heading\nHello world\n",
                    },
                    "body": "# Heading\nHello world",
                    "title": "Canonical Title",
                    "content_hash": self.content_hash,
                    "chunks": [
                        {
                            "chunk_index": 0,
                            "heading": "Heading",
                            "content": "# Heading\nHello world",
                            "content_hash": "b" * 64,
                        }
                    ],
                }
            ],
        }
        return dumps_json(response)


def test_compute_maps_one_coarse_native_call_into_existing_chunk_contract() -> None:
    module = _FakeNativeModule()
    provider = NativeNoteIndexComputeProvider(
        cast(NativeDocumentIndexComputeModule, module)
    )

    result = provider.compute(
        "---\ntitle: Canonical Title\npriority: 7\n---\n# Heading\nHello world\n",
        "Projects/Example.md",
    )

    assert result.frontmatter == {"title": "Canonical Title", "priority": 7}
    assert result.body == "# Heading\nHello world"
    assert result.title == "Canonical Title"
    assert result.content_hash == "a" * 64
    assert len(result.chunks) == 1
    assert result.chunks[0].heading_path == "Heading"
    assert result.chunks[0].text == "# Heading\nHello world"
    assert result.chunks[0].content_hash == "b" * 64
    assert result.chunks[0].token_count == 3
    assert isinstance(module.request, dict)
    assert module.request["max_chars"] == 1400
    assert module.request["overlap_chars"] == 160


def test_compute_rejects_malformed_native_hash() -> None:
    module = _FakeNativeModule()
    module.content_hash = "not-a-sha256"
    provider = NativeNoteIndexComputeProvider(
        cast(NativeDocumentIndexComputeModule, module)
    )

    with pytest.raises(
        ValueError,
        match="NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid content_hash",
    ):
        provider.compute("# Heading\n", "Projects/Example.md")
