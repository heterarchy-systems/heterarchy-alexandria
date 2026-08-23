"""Fail-closed Rust FastEmbed adapter for the existing embedding provider contract."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol, TypedDict, cast

from app.memory.application.retrieval.embeddings.embedding_contract import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_THREADS,
    EmbeddingProvider,
)
from app.memory.application.retrieval.embeddings.embedding_document import (
    EMBEDDING_DOCUMENT_INPUT_FORMAT,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_NATIVE_COMPUTE_CONTRACT_VERSION = 1
_NATIVE_EMBEDDING_VERSION = 1
_NATIVE_FASTEMBED_VERSION = "5.17.4"
_NATIVE_PROVIDER_NAME = "FASTEMBED_LOCAL"
_NATIVE_POOLING_MODE = "mean"
_NATIVE_BATCH_SIZE = 16
_E5_QUERY_PREFIX = "query: "
_E5_DOCUMENT_INPUT_FORMAT = f"{EMBEDDING_DOCUMENT_INPUT_FORMAT}+e5-passage-prefix-v1"


class _RuntimeWire(TypedDict):
    cache_directory: str | None
    threads: int


class _ModelWire(TypedDict):
    provider: str
    model: str
    provider_version: str
    pooling_mode: str
    normalize: bool
    dimensions: int
    document_input_format: str
    input_kind: str


class _DocumentWire(TypedDict):
    item_id: str
    content: str
    title: None
    heading: None


class _RequestWire(TypedDict):
    model: _ModelWire
    batch_size: int
    documents: list[_DocumentWire]


class _EnvelopeWire(TypedDict):
    contract_version: int
    embedding_version: int
    runtime: _RuntimeWire
    request: _RequestWire


# protocol-contract: structural-seam
class NativeFastEmbedModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by the Rust embedding provider."""

    def run_bulk_embedding_batch_json(self, payload: bytes) -> bytes:
        """Run one coarse document embedding request and return strict JSON bytes.

        Args:
            payload: Strict native bulk-embedding request JSON.

        Returns:
            Strict native bulk-embedding result JSON.
        """

    def embed_multilingual_e5_query(
        self,
        query_input: str,
        cache_directory: str | None,
        threads: int,
    ) -> list[float]:
        """Embed one exact E5 query input using the shared native runtime.

        Args:
            query_input: Exact E5-prefixed query text.
            cache_directory: Optional local model cache directory.
            threads: Native inference thread count.

        Returns:
            One native query embedding vector.
        """


class NativeFastEmbedEmbeddingProvider(EmbeddingProvider):
    """Implement the current embedding contract entirely through Rust FastEmbed.

    This adapter delegates exclusively to the native runtime and is the production
    FastEmbed authority after the Rust compute cutover.
    """

    def __init__(
        self,
        native_module: NativeFastEmbedModule,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        cache_dir: str | None = None,
        threads: int = DEFAULT_EMBEDDING_THREADS,
    ) -> None:
        """Initialize one validated native provider configuration.

        Args:
            native_module: Native module used by this operation.
            model_name: Model name used by this operation.
            dimensions: Dimensions used by this operation.
            cache_dir: Cache dir used by this operation.
            threads: Threads used by this operation.
        """
        if model_name != DEFAULT_EMBEDDING_MODEL:
            raise ValueError(
                "NATIVE_EMBEDDING_CONFIG_ERROR: only multilingual-e5-small is supported"
            )
        if dimensions != DEFAULT_EMBEDDING_DIMENSIONS:
            raise ValueError(
                "NATIVE_EMBEDDING_CONFIG_ERROR: native multilingual-e5-small requires "
                f"{DEFAULT_EMBEDDING_DIMENSIONS} dimensions"
            )
        if threads < 1:
            raise ValueError("NATIVE_EMBEDDING_CONFIG_ERROR: threads must be positive")
        self._native_module = native_module
        self._model_name = model_name
        self._dimensions = dimensions
        self._cache_dir = cache_dir
        self._threads = threads

    @property
    def provider_name(self) -> str:
        """Return the persisted provider identity shared with the current provider.

        Returns:
            Stable provider identity.
        """
        return _NATIVE_PROVIDER_NAME

    @property
    def model_name(self) -> str:
        """Return the multilingual E5 model identifier.

        Returns:
            Configured native model identifier.
        """
        return self._model_name

    @property
    def dimensions(self) -> int:
        """Return the validated embedding dimensions.

        Returns:
            Embedding vector dimension count.
        """
        return self._dimensions

    @property
    def provider_version(self) -> str:
        """Return the Rust FastEmbed implementation version.

        Returns:
            Rust FastEmbed crate version used for inference.
        """
        return _NATIVE_FASTEMBED_VERSION

    @property
    def pooling_mode(self) -> str:
        """Return the frozen multilingual E5 pooling contract.

        Returns:
            Stable pooling mode identifier.
        """
        return _NATIVE_POOLING_MODE

    @property
    def document_input_format(self) -> str:
        """Return the metadata composition plus E5 passage-prefix contract.

        Returns:
            Versioned document input format identifier.
        """
        return _E5_DOCUMENT_INPUT_FORMAT

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed already-composed document text through one coarse native request.

        Args:
            texts: Ordered metadata-aware document texts.

        Returns:
            Ordered native document embedding vectors.
        """
        prepared_texts = list(texts)
        if not prepared_texts:
            return []
        request = _EnvelopeWire(
            contract_version=_NATIVE_COMPUTE_CONTRACT_VERSION,
            embedding_version=_NATIVE_EMBEDDING_VERSION,
            runtime=_RuntimeWire(
                cache_directory=self._cache_dir,
                threads=self._threads,
            ),
            request=_RequestWire(
                model=self._model_wire(),
                batch_size=_NATIVE_BATCH_SIZE,
                documents=[
                    _DocumentWire(
                        item_id=f"embedding-{index}",
                        content=text,
                        title=None,
                        heading=None,
                    )
                    for index, text in enumerate(prepared_texts)
                ],
            ),
        )
        encoded = self._native_module.run_bulk_embedding_batch_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_document_vectors(
            loads_json(encoded),
            expected_count=len(prepared_texts),
            expected_dimensions=self._dimensions,
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed one query with the exact current Python E5 prefix semantics.

        Args:
            text: Search query text before E5 prefix composition.

        Returns:
            Native query embedding vector.
        """
        vector = self._native_module.embed_multilingual_e5_query(
            f"{_E5_QUERY_PREFIX}{text.strip()}",
            self._cache_dir,
            self._threads,
        )
        return _validated_vector(vector, self._dimensions, "query")

    def _model_wire(self) -> _ModelWire:
        """Execute model wire.

        Returns:
            _ModelWire result produced by model wire.
        """
        return _ModelWire(
            provider=self.provider_name,
            model=self.model_name,
            provider_version=self.provider_version,
            pooling_mode=self.pooling_mode,
            normalize=self.normalize,
            dimensions=self.dimensions,
            document_input_format=self.document_input_format,
            input_kind="e5_passage",
        )


def create_native_fastembed_embedding_provider(
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    cache_dir: str | None = None,
    threads: int = DEFAULT_EMBEDDING_THREADS,
) -> NativeFastEmbedEmbeddingProvider:
    """Create the fail-closed native embedding provider over the shared extension.

    Args:
        model_name: Native FastEmbed model identifier.
        dimensions: Required embedding dimensions.
        cache_dir: Optional local model cache directory.
        threads: Native inference thread count.

    Returns:
        Validated native FastEmbed embedding provider.
    """
    module = cast(NativeFastEmbedModule, load_native_compute_module())
    return NativeFastEmbedEmbeddingProvider(
        native_module=module,
        model_name=model_name,
        dimensions=dimensions,
        cache_dir=cache_dir,
        threads=threads,
    )


def _decode_document_vectors(
    value: JSONValue,
    expected_count: int,
    expected_dimensions: int,
) -> list[list[float]]:
    """Decode document vectors.

    Args:
        value: Value being processed.
        expected_count: Expected count used for validation.
        expected_dimensions: Expected dimensions used for validation.

    Returns:
        Decoded document vectors.
    """
    root = _object(value, "root")
    if (
        root.get("contract_version") != _NATIVE_COMPUTE_CONTRACT_VERSION
        or root.get("embedding_version") != _NATIVE_EMBEDDING_VERSION
    ):
        raise ValueError("NATIVE_EMBEDDING_OUTPUT_ERROR: invalid result version")
    records = root.get("records")
    if not isinstance(records, list) or len(records) != expected_count:
        raise ValueError("NATIVE_EMBEDDING_OUTPUT_ERROR: unexpected record cardinality")
    vectors: list[list[float]] = []
    for expected_index, record_value in enumerate(records):
        record = _object(record_value, "record")
        if record.get("input_index") != expected_index:
            raise ValueError("NATIVE_EMBEDDING_OUTPUT_ERROR: record order drift")
        if record.get("item_id") != f"embedding-{expected_index}":
            raise ValueError("NATIVE_EMBEDDING_OUTPUT_ERROR: record identity drift")
        vector_value = record.get("vector")
        if not isinstance(vector_value, list):
            raise ValueError("NATIVE_EMBEDDING_OUTPUT_ERROR: vector must be an array")
        vectors.append(
            _validated_vector(
                vector_value, expected_dimensions, f"document {expected_index}"
            )
        )
    return vectors


def _validated_vector(
    # Broad type justified: native extension output is untrusted runtime data validated element-wise.
    values: Sequence[object],
    expected_dimensions: int,
    label: str,
) -> list[float]:
    """Execute validated vector.

    Args:
        values: Values being processed.
        expected_dimensions: Expected dimensions used for validation.
        label: Label used by this operation.

    Returns:
        list[float] result produced by validated vector.
    """
    if len(values) != expected_dimensions:
        raise ValueError(
            f"NATIVE_EMBEDDING_OUTPUT_ERROR: {label} vector has unexpected dimensions"
        )
    vector: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(
                f"NATIVE_EMBEDDING_OUTPUT_ERROR: {label} vector contains a non-number"
            )
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(
                f"NATIVE_EMBEDDING_OUTPUT_ERROR: {label} vector contains a non-finite value"
            )
        vector.append(number)
    return vector


def _object(value: JSONValue, label: str) -> JSONObject:
    """Execute object.

    Args:
        value: Value being processed.
        label: Label used by this operation.

    Returns:
        JSONObject result produced by object.
    """
    if not isinstance(value, dict):
        raise ValueError(f"NATIVE_EMBEDDING_OUTPUT_ERROR: {label} must be an object")
    return value
