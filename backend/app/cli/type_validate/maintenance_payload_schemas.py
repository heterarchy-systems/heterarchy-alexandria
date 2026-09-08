"""Pydantic payload contracts for maintenance CLI output shaping."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, field_validator

from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.type_validation.strict_json_value import model_validate_json_value
from app.shared.types.extra_types import JSONObject, JSONValue


class CliPayloadSchema(StrictSchemaModel):
    """Base schema for partial backend/MCP payload validation."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        use_enum_values=True,
        validate_default=True,
    )


class McpSmokePayload(CliPayloadSchema):
    """Validated subset of an MCP smoke-check payload."""

    ok: bool = False
    mcp_url: JSONValue | None = None
    required_tools: Annotated[
        tuple[JSONValue, ...],
        described_field("Required tools for this MCP smoke payload."),
    ] = ()
    missing_tools: Annotated[
        tuple[JSONValue, ...],
        described_field("Missing tools for this MCP smoke payload."),
    ] = ()
    tool_count: JSONValue | None = None


class RagStatusPayload(CliPayloadSchema):
    """Validated subset of Memory Steward RAG health fields."""

    fts: JSONValue | None = None
    vector: JSONValue | None = None
    embedding: JSONValue | None = None


class CurrentCompactPayload(CliPayloadSchema):
    """Validated subset of CURRENT Memory Compact freshness fields."""

    id: JSONValue | None = None
    age_days: JSONValue | None = None
    max_age_days: JSONValue | None = None


class CurrentCompactReviewPayload(CliPayloadSchema):
    """Validated subset of the CURRENT Memory Compact review."""

    compact_id: str | None = None
    verdict: str | None = None
    total_score: int | None = None
    max_score: int | None = None
    recommended_actions: Annotated[
        tuple[str, ...],
        described_field("Recommended actions for this compact review payload."),
    ] = ()

    @field_validator("recommended_actions", mode="before")
    @classmethod
    def _filter_recommended_actions(cls, value: JSONValue) -> JSONValue:
        """Keep only string review actions at the CLI boundary."""
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value


class NextActionPayload(CliPayloadSchema):
    """Validated subset of a recommended maintenance next action."""

    code: JSONValue | None = None
    tool: JSONValue | None = None


class ReadinessPayload(CliPayloadSchema):
    """Validated subset of Memory Steward readiness payloads."""

    ready: bool | None = None
    warnings: Annotated[
        tuple[JSONValue, ...], described_field("Warnings for this readiness payload.")
    ] = ()
    rag: Annotated[
        RagStatusPayload, described_field("RAG for this readiness payload.")
    ] = RagStatusPayload()
    current_memory_compact: Annotated[
        CurrentCompactPayload,
        described_field("Current memory compact for this readiness payload."),
    ] = CurrentCompactPayload()
    current_memory_compact_review: CurrentCompactReviewPayload | None = None
    next_actions: Annotated[
        tuple[NextActionPayload, ...],
        described_field("Next actions for this readiness payload."),
    ] = ()

    @field_validator("next_actions", mode="before")
    @classmethod
    def _filter_next_action_objects(cls, value: JSONValue) -> JSONValue:
        """Keep object-shaped next actions at the CLI boundary."""
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value


class CreatedCompactPayload(CliPayloadSchema):
    """Validated subset of compact creation result fields."""

    id: JSONValue | None = None


class PreflightPayload(CliPayloadSchema):
    """Validated subset of Memory Steward preflight/refresh payloads."""

    status: JSONValue | None = None
    refresh_required: JSONValue | None = None
    created: CreatedCompactPayload | None = None
    post_refresh_readiness: ReadinessPayload | None = None
    readiness: ReadinessPayload | None = None

    def current_readiness(self) -> ReadinessPayload:
        """Return the strongest readiness payload embedded in the response."""
        return self.post_refresh_readiness or self.readiness or ReadinessPayload()


class CombinedCheckPayload(CliPayloadSchema):
    """Validated subset of combined maintenance check payloads."""

    ok: bool = False


def validate_mcp_smoke_payload(payload: JSONValue) -> McpSmokePayload:
    """Validate an MCP smoke payload."""
    return model_validate_json_value(McpSmokePayload, _object_or_empty(payload))


def validate_preflight_payload(payload: JSONValue) -> PreflightPayload:
    """Validate a Memory Steward preflight payload."""
    return model_validate_json_value(PreflightPayload, _object_or_empty(payload))


def validate_combined_check_payload(payload: JSONValue) -> CombinedCheckPayload:
    """Validate a combined maintenance check payload."""
    return model_validate_json_value(CombinedCheckPayload, _object_or_empty(payload))


def _object_or_empty(payload: JSONValue) -> JSONObject:
    """Return an object payload or an empty object."""
    if isinstance(payload, dict):
        return payload
    return {}


class MaintenanceCheckSummaryPayload(CliPayloadSchema):
    """Output schema for compact MCP plus Memory Steward preflight summaries."""

    ok: bool
    mcp_url: JSONValue | None = None
    mcp_tool_count: JSONValue | None = None
    mcp_required_tools_count: int
    mcp_required_tools: Annotated[
        tuple[JSONValue, ...],
        described_field(
            "MCP required tools for this maintenance check summary payload."
        ),
    ] = ()
    mcp_missing_tools: Annotated[
        tuple[JSONValue, ...],
        described_field(
            "MCP missing tools for this maintenance check summary payload."
        ),
    ] = ()
    preflight_status: JSONValue | None = None
    refresh_required: JSONValue | None = None
    created: bool
    created_compact_id: JSONValue | None = None
    ready: bool | None = None
    warnings: Annotated[
        tuple[JSONValue, ...],
        described_field("Warnings for this maintenance check summary payload."),
    ] = ()
    current_compact_id: JSONValue | None = None
    compact_age_days: JSONValue | None = None
    max_compact_age_days: JSONValue | None = None
    rag_fts: JSONValue | None = None
    rag_vector: JSONValue | None = None
    rag_embedding: JSONValue | None = None
    current_compact_review_verdict: str | None = None
    current_compact_review_total_score: int | None = None
    current_compact_review_max_score: int | None = None
    current_compact_review_recommended_actions: Annotated[
        tuple[str, ...],
        described_field("Recommended actions from the current compact review."),
    ] = ()
    next_actions_count: int
    next_action: JSONValue | None = None
    next_action_tool: JSONValue | None = None


class MaintenanceCheckPayload(CliPayloadSchema):
    """Output schema for full MCP plus Memory Steward preflight checks."""

    ok: bool
    mcp_smoke: JSONValue
    preflight: JSONValue
