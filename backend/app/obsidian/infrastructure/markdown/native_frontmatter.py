"""Native Rust adapter for Markdown document/frontmatter parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, cast

from app.obsidian.infrastructure.markdown.frontmatter import (
    FrontmatterScalar,
    FrontmatterValue,
    MarkdownDocument,
)
from app.shared.infrastructure.native_compute_extension import (
    NativeComputeContractModule,
    load_native_compute_module,
)
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONObject, JSONValue

_NATIVE_ANALYSIS_VERSION = 1
_DOCUMENT_ID = "obsidian-markdown-document"
_RELATIVE_PATH = "Obsidian/Document.md"


class _DocumentWire(TypedDict):
    document_id: str
    relative_path: str
    text: str


class _DocumentBatchWire(TypedDict):
    contract_version: int
    documents: list[_DocumentWire]


# protocol-contract: structural-seam
class NativeDocumentAnalysisModule(NativeComputeContractModule, Protocol):
    """Native extension surface required by frontmatter parsing."""

    def analyze_document_batch_json(self, payload: bytes) -> bytes:
        """Analyze one strict JSON document batch.

        Args:
            payload: Strict native document-analysis request JSON.

        Returns:
            Strict native document-analysis result JSON.
        """


@dataclass(frozen=True, slots=True)
class NativeMarkdownDocumentParser:
    """Map native document analysis into the existing MarkdownDocument DTO."""

    native_module: NativeDocumentAnalysisModule

    def parse(self, text: str) -> MarkdownDocument:
        """Return Python-compatible parsed frontmatter and body.

        Args:
            text: Complete Markdown document.

        Returns:
            Existing immutable MarkdownDocument DTO.

        Raises:
            ValueError: If native parsing fails or the wire contract drifts.
        """
        request = _DocumentBatchWire(
            contract_version=1,
            documents=[
                _DocumentWire(
                    document_id=_DOCUMENT_ID,
                    relative_path=_RELATIVE_PATH,
                    text=text,
                )
            ],
        )
        encoded = self.native_module.analyze_document_batch_json(
            dumps_json(cast(JSONValue, request))
        )
        return _decode_document(loads_json(encoded))


def create_native_markdown_document_parser() -> NativeMarkdownDocumentParser:
    """Create a fail-closed Markdown parser over the shared native module.

    Returns:
        Native Markdown document parser.
    """
    module = cast(NativeDocumentAnalysisModule, load_native_compute_module())
    return NativeMarkdownDocumentParser(module)


def _decode_document(value: JSONValue) -> MarkdownDocument:
    """Decode document.

    Args:
        value: Value being processed.

    Returns:
        Decoded document.
    """
    root = _object(value, "root")
    if (
        root.get("contract_version") != 1
        or root.get("analysis_version") != _NATIVE_ANALYSIS_VERSION
    ):
        raise ValueError(
            "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid contract version"
        )
    results = _array(root.get("results"), "results")
    if len(results) != 1:
        raise ValueError(
            "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: expected one document result"
        )
    result = _object(results[0], "result")
    status = result.get("status")
    if status == "error":
        error = _object(result.get("error"), "error")
        message = error.get("message")
        if not isinstance(message, str):
            raise ValueError(
                "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid native error"
            )
        raise ValueError(message)
    if status != "success":
        raise ValueError("NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid result status")
    analysis = _object(result.get("analysis"), "analysis")
    if analysis.get("analysis_version") != _NATIVE_ANALYSIS_VERSION:
        raise ValueError(
            "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid analysis version"
        )
    body = analysis.get("body")
    if not isinstance(body, str):
        raise ValueError("NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid body")
    frontmatter = decode_native_frontmatter_entries(analysis.get("frontmatter"))
    return MarkdownDocument(frontmatter=frontmatter, body=body)


def decode_native_frontmatter_entries(
    value: JSONValue | None,
) -> dict[str, FrontmatterValue]:
    """Decode tagged native frontmatter entries into Python-compatible values.

    Args:
        value: Native ``frontmatter`` array from a document-analysis result.

    Returns:
        Ordered Python-compatible frontmatter mapping.

    Raises:
        ValueError: If the native tagged-value contract is malformed.
    """
    entries = _array(value, "frontmatter")
    frontmatter: dict[str, FrontmatterValue] = {}
    for raw_entry in entries:
        entry = _object(raw_entry, "frontmatter entry")
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(
                "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid frontmatter key"
            )
        if key in frontmatter:
            raise ValueError(
                "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: duplicate frontmatter key"
            )
        frontmatter[key] = _frontmatter_value(entry.get("value"))
    return frontmatter


def _frontmatter_value(value: JSONValue | None) -> FrontmatterValue:
    """Execute frontmatter value.

    Args:
        value: Value being processed.

    Returns:
        FrontmatterValue result produced by frontmatter value.
    """
    tagged = _object(value, "frontmatter value")
    kind = tagged.get("kind")
    raw = tagged.get("value")
    if kind == "sequence":
        return tuple(_frontmatter_scalar(item) for item in _array(raw, "sequence"))
    return _scalar_from_tag(kind, raw)


def _frontmatter_scalar(value: JSONValue) -> FrontmatterScalar:
    """Execute frontmatter scalar.

    Args:
        value: Value being processed.

    Returns:
        FrontmatterScalar result produced by frontmatter scalar.
    """
    tagged = _object(value, "frontmatter scalar")
    return _scalar_from_tag(tagged.get("kind"), tagged.get("value"))


def _scalar_from_tag(
    kind: JSONValue | None, raw: JSONValue | None
) -> FrontmatterScalar:
    """Execute scalar from tag.

    Args:
        kind: Kind used by this operation.
        raw: Raw used by this operation.

    Returns:
        FrontmatterScalar result produced by scalar from tag.
    """
    if kind == "null":
        if raw is not None:
            raise ValueError(
                "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: null scalar has a value"
            )
        return None
    if kind == "string":
        if isinstance(raw, str):
            return raw
    elif kind == "integer":
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(
                    "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid integer scalar"
                ) from exc
    elif kind == "float":
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError as exc:
                raise ValueError(
                    "NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid float scalar"
                ) from exc
    elif kind == "boolean" and isinstance(raw, bool):
        return raw
    raise ValueError("NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: invalid tagged scalar")


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
            f"NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: {field} must be an object"
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
            f"NATIVE_DOCUMENT_ANALYSIS_OUTPUT_ERROR: {field} must be an array"
        )
    return value
