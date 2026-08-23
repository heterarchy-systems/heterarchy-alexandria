"""Parsing helpers for Memory Steward readiness payload contracts."""

from __future__ import annotations

from app.mcp_server.type_validate.memory.memory_steward_readiness_schemas import (
    CompactRefreshDraftPayload,
    CurrentCompactPayload,
    RagStatusPayload,
    ReadinessSummaryPayload,
    ReviewQueuePayload,
)
from app.shared.type_validation.strict_json_value import model_validate_json_value
from app.shared.types.extra_types import JSONObject, JSONValue


def result_object(payload: JSONValue) -> JSONObject:
    """Return a backend result object or the payload object itself.

    Args:
        payload: Backend JSON payload, optionally wrapped in a result field.

    Returns:
        JSON object suitable for Pydantic validation.
    """
    root = _object_or_empty(payload)
    result = root.get("result")
    if isinstance(result, dict):
        return result
    return root


def parse_rag_status(payload: JSONValue) -> RagStatusPayload:
    """Validate RAG status payload.

    Args:
        payload: Backend RAG status payload.

    Returns:
        Validated RAG status fields.
    """
    return model_validate_json_value(RagStatusPayload, result_object(payload))


def parse_current_compact(payload: JSONValue) -> CurrentCompactPayload:
    """Validate CURRENT Memory Compact payload.

    Args:
        payload: Backend current compact payload.

    Returns:
        Validated compact fields.
    """
    return model_validate_json_value(CurrentCompactPayload, result_object(payload))


def parse_review_queue(payload: JSONValue) -> ReviewQueuePayload:
    """Validate vault review queue payload.

    Args:
        payload: Backend review queue payload.

    Returns:
        Validated review queue fields.
    """
    return model_validate_json_value(ReviewQueuePayload, result_object(payload))


def parse_readiness_summary(payload: JSONValue) -> ReadinessSummaryPayload:
    """Validate Memory Steward readiness summary payload.

    Args:
        payload: Readiness summary payload.

    Returns:
        Validated readiness summary fields.
    """
    return model_validate_json_value(ReadinessSummaryPayload, result_object(payload))


def source_ref_dicts(draft: CompactRefreshDraftPayload) -> list[dict[str, str]]:
    """Return compact source refs as create-request dictionaries.

    Args:
        draft: Validated compact refresh draft.

    Returns:
        Source reference dictionaries accepted by compact creation.
    """
    return [ref.model_dump(mode="json") for ref in draft.source_refs]


def _object_or_empty(payload: JSONValue) -> JSONObject:
    """Execute object or empty.

    Args:
        payload: Validated payload for this operation.

    Returns:
        JSONObject result produced by object or empty.
    """
    if isinstance(payload, dict):
        return payload
    return {}
