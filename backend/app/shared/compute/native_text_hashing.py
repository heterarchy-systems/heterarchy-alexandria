"""Native Rust batch adapter for canonical UTF-8 SHA-256 text hashing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_NATIVE_HASHING_VERSION = 1


@dataclass(frozen=True, slots=True)
class TextHashInput:
    """One typed text-hash batch item."""

    document_id: str
    relative_path: str
    text: str


@dataclass(frozen=True, slots=True)
class TextHashResult:
    """One canonical SHA-256 hash result."""

    document_id: str
    relative_path: str
    content_hash: str


class _DocumentWire(TypedDict):
    document_id: str
    relative_path: str
    text: str
    embedding_fingerprint: None
    indexed_at: None
    previous: _PreviousWire
    current_chunk_identities: None
    current_edge_identities: None


class _HashBatchWire(TypedDict):
    contract_version: int
    hashing_version: int
    documents: list[_DocumentWire]


class _PreviousWire(TypedDict):
    content_hash: None
    embedding_fingerprint_key: None
    chunk_identities: None
    edge_identities: None


# protocol-contract: structural-seam
class NativeHashComputeModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by canonical text hashing."""

    def compute_hash_batch_json(self, payload: bytes) -> bytes:
        """Hash one strict batch.

        Args:
            payload: Strict native hash/fingerprint request JSON.

        Returns:
            Strict native hash/fingerprint result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeTextHashBatcher:
    """Compute canonical hashes in one coarse native batch."""

    native_module: NativeHashComputeModule

    def hash_texts(
        self, items: tuple[TextHashInput, ...]
    ) -> tuple[TextHashResult, ...]:
        """Return canonical SHA-256 hashes in input order.

        Args:
            items: Typed document identities, paths, and raw text.

        Returns:
            Canonical content hashes in deterministic input order.

        Raises:
            ValueError: If native output violates the hashing wire contract.
        """
        request = _HashBatchWire(
            contract_version=1,
            hashing_version=_NATIVE_HASHING_VERSION,
            documents=[_document_wire(item) for item in items],
        )
        encoded = self.native_module.compute_hash_batch_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_results(loads_json(encoded), expected_items=items)


def create_native_text_hash_batcher() -> NativeTextHashBatcher:
    """Create the fail-closed batch hasher over the shared native module.

    Returns:
        Native canonical text hash batcher.
    """
    module = cast(NativeHashComputeModule, load_native_compute_module())
    return NativeTextHashBatcher(module)


def hash_text(text: str) -> str:
    """Return the Rust-computed canonical SHA-256 digest for one UTF-8 text value.

    Args:
        text: Text value to hash exactly as supplied.

    Returns:
        Lowercase canonical SHA-256 hexadecimal digest.
    """
    return hash_texts((text,))[0]


def hash_texts(texts: tuple[str, ...]) -> tuple[str, ...]:
    """Return Rust-computed canonical SHA-256 digests in input order.

    Args:
        texts: Text values to hash exactly as supplied.

    Returns:
        Lowercase canonical SHA-256 hexadecimal digests in input order.
    """
    if not texts:
        return ()
    items = tuple(
        TextHashInput(
            document_id=f"text-{index}",
            relative_path=f"text/{index}",
            text=text,
        )
        for index, text in enumerate(texts)
    )
    return tuple(
        result.content_hash
        for result in create_native_text_hash_batcher().hash_texts(items)
    )


def _document_wire(item: TextHashInput) -> _DocumentWire:
    """Execute document wire.

    Args:
        item: Item being processed.

    Returns:
        _DocumentWire result produced by document wire.
    """
    return _DocumentWire(
        document_id=item.document_id,
        relative_path=item.relative_path,
        text=item.text,
        embedding_fingerprint=None,
        indexed_at=None,
        previous=_PreviousWire(
            content_hash=None,
            embedding_fingerprint_key=None,
            chunk_identities=None,
            edge_identities=None,
        ),
        current_chunk_identities=None,
        current_edge_identities=None,
    )


def _decode_results(
    value: JSONValue,
    expected_items: tuple[TextHashInput, ...],
) -> tuple[TextHashResult, ...]:
    """Decode results.

    Args:
        value: Value being processed.
        expected_items: Expected items used for validation.

    Returns:
        Decoded results.
    """
    root = _object(value, "root")
    if (
        root.get("contract_version") != 1
        or root.get("hashing_version") != _NATIVE_HASHING_VERSION
    ):
        raise ValueError("NATIVE_HASH_COMPUTE_OUTPUT_ERROR: invalid contract version")
    raw_results = _array(root.get("results"), "results")
    if len(raw_results) != len(expected_items):
        raise ValueError("NATIVE_HASH_COMPUTE_OUTPUT_ERROR: result cardinality drift")
    results: list[TextHashResult] = []
    for expected, raw_result in zip(expected_items, raw_results, strict=True):
        result = _object(raw_result, "result")
        document_id = _text(result, "document_id")
        relative_path = _text(result, "relative_path")
        content_hash = _text(result, "content_hash")
        if (
            document_id != expected.document_id
            or relative_path != expected.relative_path
        ):
            raise ValueError("NATIVE_HASH_COMPUTE_OUTPUT_ERROR: result identity drift")
        if len(content_hash) != 64:
            raise ValueError("NATIVE_HASH_COMPUTE_OUTPUT_ERROR: invalid SHA-256 digest")
        results.append(
            TextHashResult(
                document_id=document_id,
                relative_path=relative_path,
                content_hash=content_hash,
            )
        )
    return tuple(results)


def _object(value: JSONValue | None, field: str) -> JSONObject:
    """Execute object.

    Args:
        value: Value being processed.
        field: Field used by this operation.

    Returns:
        JSONObject result produced by object.
    """
    if not isinstance(value, dict):
        raise ValueError(f"NATIVE_HASH_COMPUTE_OUTPUT_ERROR: {field} must be an object")
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
        raise ValueError(f"NATIVE_HASH_COMPUTE_OUTPUT_ERROR: {field} must be an array")
    return value


def _text(value: JSONObject, key: str) -> str:
    """Execute text.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str result produced by text.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"NATIVE_HASH_COMPUTE_OUTPUT_ERROR: invalid {key}")
    return raw
