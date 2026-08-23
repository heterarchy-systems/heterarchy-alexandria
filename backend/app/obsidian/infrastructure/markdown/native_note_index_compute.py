"""Native Rust adapter for coarse Obsidian document-index compute."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianChunkIndex
from app.obsidian.infrastructure.markdown.native_frontmatter import (
    decode_native_frontmatter_entries,
)
from app.obsidian.infrastructure.markdown.note_index_compute_contracts import (
    NoteIndexComputeProvider,
    NoteIndexComputeResult,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.search.markdown_text_chunking import (
    DEFAULT_SEARCH_CHUNK_MAX_CHARS,
    DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.utils.text_metrics import count_word_tokens

_DOCUMENT_INDEX_CONTRACT_VERSION = 1
_DOCUMENT_ANALYSIS_VERSION = 1
_DOCUMENT_CHUNKING_VERSION = 1
_DOCUMENT_HASHING_VERSION = 1
_DOCUMENT_ID = "obsidian-note-index-document"


class _DocumentIndexInputWire(TypedDict):
    document_id: str
    relative_path: str
    text: str


class _DocumentIndexBatchWire(TypedDict):
    contract_version: int
    chunking_version: int
    hashing_version: int
    max_chars: int
    overlap_chars: int
    documents: list[_DocumentIndexInputWire]


# protocol-contract: structural-seam
class NativeDocumentIndexComputeModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by coarse note-index compute."""

    def compute_document_index_batch_json(self, payload: bytes) -> bytes:
        """Compute analysis, chunking, and hashes for one strict JSON batch.

        Args:
            payload: Strict native note-index compute request JSON.

        Returns:
            Strict native note-index compute result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeNoteIndexComputeProvider(NoteIndexComputeProvider):
    """Delegate deterministic note-index compute to the native Rust extension."""

    native_module: NativeDocumentIndexComputeModule

    def compute(self, text: str, relative_path: str) -> NoteIndexComputeResult:
        """Return parsed document, title, chunks, and hashes from one native call.

        Args:
            text: Complete Markdown document already read by Python.
            relative_path: Vault-relative path used for deterministic title fallback.

        Returns:
            Frozen normalized note-index compute result.

        Raises:
            ValueError: If native compute fails or its wire contract drifts.
        """
        request = _DocumentIndexBatchWire(
            contract_version=_DOCUMENT_INDEX_CONTRACT_VERSION,
            chunking_version=_DOCUMENT_CHUNKING_VERSION,
            hashing_version=_DOCUMENT_HASHING_VERSION,
            max_chars=DEFAULT_SEARCH_CHUNK_MAX_CHARS,
            overlap_chars=DEFAULT_SEARCH_CHUNK_OVERLAP_CHARS,
            documents=[
                _DocumentIndexInputWire(
                    document_id=_DOCUMENT_ID,
                    relative_path=relative_path,
                    text=text,
                )
            ],
        )
        encoded = self.native_module.compute_document_index_batch_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_result(loads_json(encoded))


def create_native_note_index_compute_provider() -> NativeNoteIndexComputeProvider:
    """Create a fail-closed note-index compute provider over the native module.

    Returns:
        Native note-index compute provider.
    """
    module = cast(NativeDocumentIndexComputeModule, load_native_compute_module())
    return NativeNoteIndexComputeProvider(module)


def _decode_result(value: JSONValue) -> NoteIndexComputeResult:
    """Decode result.

    Args:
        value: Value being processed.

    Returns:
        Decoded result.
    """
    root = _object(value, "root")
    if (
        root.get("contract_version") != _DOCUMENT_INDEX_CONTRACT_VERSION
        or root.get("analysis_version") != _DOCUMENT_ANALYSIS_VERSION
        or root.get("chunking_version") != _DOCUMENT_CHUNKING_VERSION
        or root.get("hashing_version") != _DOCUMENT_HASHING_VERSION
    ):
        raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid contract version")
    results = _array(root.get("results"), "results")
    if len(results) != 1:
        raise ValueError(
            "NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: expected one document result"
        )
    result = _object(results[0], "result")
    status = result.get("status")
    if status == "error":
        error = _object(result.get("error"), "error")
        message = error.get("message")
        if not isinstance(message, str):
            raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid native error")
        raise ValueError(message)
    if status != "success":
        raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid result status")
    analysis = _object(result.get("analysis"), "analysis")
    if analysis.get("analysis_version") != _DOCUMENT_ANALYSIS_VERSION:
        raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid analysis version")
    body = _required_text_allow_empty(result, "body")
    title = _required_text(result, "title")
    content_hash = _sha256_hex(result, "content_hash")
    frontmatter = decode_native_frontmatter_entries(analysis.get("frontmatter"))
    raw_chunks = _array(result.get("chunks"), "chunks")
    chunks = tuple(
        _chunk(raw_chunk, expected_index=index)
        for index, raw_chunk in enumerate(raw_chunks)
    )
    if not chunks:
        raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: missing chunks")
    return NoteIndexComputeResult(
        frontmatter=frontmatter,
        body=body,
        title=title,
        content_hash=content_hash,
        chunks=chunks,
    )


def _chunk(value: JSONValue, expected_index: int) -> ObsidianChunkIndex:
    """Execute chunk.

    Args:
        value: Value being processed.
        expected_index: Expected index used for validation.

    Returns:
        ObsidianChunkIndex result produced by chunk.
    """
    chunk = _object(value, "chunk")
    chunk_index = chunk.get("chunk_index")
    if chunk_index != expected_index or isinstance(chunk_index, bool):
        raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid chunk index")
    heading = chunk.get("heading")
    if heading is not None and not isinstance(heading, str):
        raise ValueError("NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid chunk heading")
    content = _required_text_allow_empty(chunk, "content")
    return ObsidianChunkIndex(
        chunk_index=expected_index,
        heading_path=heading,
        text=content,
        content_hash=_sha256_hex(chunk, "content_hash"),
        token_count=count_word_tokens(content),
    )


def _sha256_hex(value: JSONObject, key: str) -> str:
    """Execute sha256 hex.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by sha256 hex.
    """
    digest = _required_text(value, key)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid {key}")
    return digest


def _required_text(value: JSONObject, key: str) -> str:
    """Execute required text.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by required text.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid {key}")
    return raw


def _required_text_allow_empty(value: JSONObject, key: str) -> str:
    """Execute required text allow empty.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by required text allow empty.
    """
    raw = value.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: invalid {key}")
    return raw


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
            f"NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: {field} must be an object"
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
            f"NATIVE_DOCUMENT_INDEX_OUTPUT_ERROR: {field} must be an array"
        )
    return value
