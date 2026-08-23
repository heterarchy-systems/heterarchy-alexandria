"""Native Rust adapter for deterministic Markdown search chunking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.search.markdown_text_chunking import SearchTextChunk
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_NATIVE_CHUNKING_VERSION = 1
_DOCUMENT_ID = "shared-markdown-chunk"
_RELATIVE_PATH = "Shared/Search.md"


class _ChunkDocumentWire(TypedDict):
    document_id: str
    relative_path: str
    title: str
    content: str


class _ChunkBatchWire(TypedDict):
    contract_version: int
    chunking_version: int
    max_chars: int
    overlap_chars: int
    documents: list[_ChunkDocumentWire]


# protocol-contract: structural-seam
class NativeMarkdownChunkingModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by shared Markdown chunking."""

    def chunk_markdown_batch_json(self, payload: bytes) -> bytes:
        """Chunk one strict JSON batch.

        Args:
            payload: Strict native chunking request JSON.

        Returns:
            Strict native chunking result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeMarkdownTextChunker:
    """Map native chunk output into the existing shared chunk DTO."""

    native_module: NativeMarkdownChunkingModule

    def split(
        self,
        title: str,
        content: str,
        max_chars: int,
        overlap_chars: int,
    ) -> list[SearchTextChunk]:
        """Return deterministic Rust-computed Markdown chunks.

        Args:
            title: Document title used as fallback heading.
            content: Markdown body.
            max_chars: Maximum characters in one chunk.
            overlap_chars: Target overlap carried between large-section chunks.

        Returns:
            Existing shared search chunk DTOs in native result order.

        Raises:
            ValueError: If native output violates the chunking wire contract.
        """
        request = _ChunkBatchWire(
            contract_version=1,
            chunking_version=_NATIVE_CHUNKING_VERSION,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            documents=[
                _ChunkDocumentWire(
                    document_id=_DOCUMENT_ID,
                    relative_path=_RELATIVE_PATH,
                    title=title,
                    content=content,
                )
            ],
        )
        encoded = self.native_module.chunk_markdown_batch_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_chunks(loads_json(encoded))


def create_native_markdown_text_chunker() -> NativeMarkdownTextChunker:
    """Create a fail-closed Markdown chunker over the shared native module.

    Returns:
        Native Markdown chunker.
    """
    module = cast(NativeMarkdownChunkingModule, load_native_compute_module())
    return NativeMarkdownTextChunker(module)


def _decode_chunks(value: JSONValue) -> list[SearchTextChunk]:
    """Decode chunks.

    Args:
        value: Value being processed.

    Returns:
        list[SearchTextChunk] result produced by decode chunks.
    """
    root = _object(value, "root")
    if root.get("contract_version") != 1:
        raise ValueError(
            "NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: invalid contract version"
        )
    if root.get("chunking_version") != _NATIVE_CHUNKING_VERSION:
        raise ValueError(
            "NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: invalid chunking version"
        )
    results = _array(root.get("results"), "results")
    if len(results) != 1:
        raise ValueError(
            "NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: expected one document result"
        )
    result = _object(results[0], "result")
    if result.get("status") != "success":
        raise ValueError(
            "NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: native document failed"
        )
    raw_chunks = _array(result.get("chunks"), "chunks")
    return [
        _chunk(raw_chunk, expected_index=index)
        for index, raw_chunk in enumerate(raw_chunks)
    ]


def _chunk(value: JSONValue, expected_index: int) -> SearchTextChunk:
    """Execute chunk.

    Args:
        value: Value being processed.
        expected_index: Expected index used by this operation.

    Returns:
        SearchTextChunk result produced by chunk.
    """
    chunk = _object(value, "chunk")
    chunk_index = chunk.get("chunk_index")
    heading = chunk.get("heading")
    content = chunk.get("content")
    if chunk_index != expected_index or isinstance(chunk_index, bool):
        raise ValueError("NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: invalid chunk index")
    if heading is not None and not isinstance(heading, str):
        raise ValueError("NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: invalid heading")
    if not isinstance(content, str):
        raise ValueError("NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: invalid content")
    return SearchTextChunk(chunk_index=expected_index, heading=heading, content=content)


def _object(value: JSONValue | None, field: str) -> JSONObject:
    """Execute object.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        JSONObject result produced by object.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: {field} must be an object"
        )
    return value


def _array(value: JSONValue | None, field: str) -> list[JSONValue]:
    """Execute array.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        list[JSONValue] result produced by array.
    """
    if not isinstance(value, list):
        raise ValueError(
            f"NATIVE_MARKDOWN_CHUNKING_OUTPUT_ERROR: {field} must be an array"
        )
    return value
