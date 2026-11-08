"""Pydantic contracts and policy helpers for Memory Steward readiness tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from app.shared.schemas.common_schemas import StrictSchemaModel
from app.shared.types.extra_types import JSONValue


class MemoryStewardReadinessPayload(StrictSchemaModel):
    """Base payload schema for partial Memory Steward readiness validation."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        use_enum_values=True,
        validate_default=True,
    )


class RagStatusPayload(MemoryStewardReadinessPayload):
    """Validated RAG status fields used by readiness."""

    fts: str | None = None
    vector: str | None = None
    embedding: str | None = None
    warnings: Annotated[
        tuple[str, ...], Field(description="Warnings for this RAG status payload.")
    ] = ()

    @field_validator("warnings", mode="before")
    @classmethod
    def _filter_warning_strings(cls, value: JSONValue) -> JSONValue:
        """Keep only string entries when warnings arrive as a JSON list.

        Args:
            value: Raw warnings field value.

        Returns:
            Tuple of string warning items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value


class CurrentCompactSourceRefPayload(MemoryStewardReadinessPayload):
    """Validated current compact source-ref freshness fields."""

    source_id: JSONValue | None = None
    detail_path: JSONValue | None = None
    source_hash: str | None = None
    current_source_hash: str | None = None

    def hash_mismatched(self) -> bool:
        """Return whether stored and current source hashes conflict.

        Returns:
            True when both hashes are present and different.
        """
        return (
            self.source_hash is not None
            and self.current_source_hash is not None
            and self.source_hash != self.current_source_hash
        )


class CurrentCompactPayload(MemoryStewardReadinessPayload):
    """Validated CURRENT Memory Compact fields used by readiness."""

    id: JSONValue | None = None
    project: JSONValue | None = None
    status: JSONValue | None = None
    updated_at: str | None = None
    age_days: int | None = None
    max_age_days: int | None = None
    warnings: Annotated[
        tuple[str, ...], Field(description="Warnings for this current compact payload.")
    ] = ()
    source_refs: Annotated[
        tuple[CurrentCompactSourceRefPayload, ...],
        Field(description="Source refs for this current compact payload."),
    ] = ()

    @field_validator("warnings", mode="before")
    @classmethod
    def _filter_warning_strings(cls, value: JSONValue) -> JSONValue:
        """Keep only string entries when warnings arrive as a JSON list.

        Args:
            value: Raw warnings field value.

        Returns:
            Tuple of string warning items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value

    @field_validator("source_refs", mode="before")
    @classmethod
    def _filter_source_ref_objects(cls, value: JSONValue) -> JSONValue:
        """Keep only dictionary entries when source_refs arrive as a JSON list.

        Args:
            value: Raw source_refs field value.

        Returns:
            Tuple of dictionary source-ref items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value

    def calculated_age_days(self) -> int | None:
        """Calculate compact age from updated_at when possible.

        Returns:
            Non-negative age in days, or None when timestamp evidence is absent.
        """
        if self.updated_at is None:
            return None
        try:
            updated = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if updated.tzinfo is None or updated.utcoffset() is None:
            updated = updated.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        return max((now - updated.astimezone(UTC)).days, 0)

    def has_source_hash_mismatch(self) -> bool:
        """Return whether attached source evidence reports changed content.

        Returns:
            True when any source ref includes both the compact-time hash and a
            current observed hash and they differ.
        """
        return any(source_ref.hash_mismatched() for source_ref in self.source_refs)


class CurrentCompactReviewScorePayload(MemoryStewardReadinessPayload):
    """Validated current compact review rubric score."""

    code: str | None = None
    label: str | None = None
    score: int | None = None
    required: bool | None = None
    reasons: Annotated[
        tuple[str, ...],
        Field(description="Reasons for this current compact review score payload."),
    ] = ()

    @field_validator("reasons", mode="before")
    @classmethod
    def _filter_reason_strings(cls, value: JSONValue) -> JSONValue:
        """Keep only string entries when rubric reasons arrive as a JSON list.

        Args:
            value: Raw reasons field value.

        Returns:
            Tuple of string reason items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value


class CurrentCompactReviewPayload(MemoryStewardReadinessPayload):
    """Validated current compact vault review summary."""

    compact_id: str | None = None
    verdict: str | None = None
    total_score: int | None = None
    max_score: int | None = None
    scores: Annotated[
        tuple[CurrentCompactReviewScorePayload, ...],
        Field(description="Scores for this current compact review payload."),
    ] = ()
    missing_refs: Annotated[
        tuple[str, ...],
        Field(description="Missing refs for this current compact review payload."),
    ] = ()
    contradictions: Annotated[
        tuple[str, ...],
        Field(description="Contradictions for this current compact review payload."),
    ] = ()
    stale_reasons: Annotated[
        tuple[str, ...],
        Field(description="Stale reasons for this current compact review payload."),
    ] = ()
    recommended_actions: Annotated[
        tuple[str, ...],
        Field(
            description="Recommended actions for this current compact review payload."
        ),
    ] = ()

    @field_validator(
        "missing_refs",
        "contradictions",
        "stale_reasons",
        "recommended_actions",
        mode="before",
    )
    @classmethod
    def _filter_strings(cls, value: JSONValue) -> JSONValue:
        """Keep only string entries when review list fields arrive as a JSON list.

        Args:
            value: Raw review list field value.

        Returns:
            Tuple of string items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value

    @field_validator("scores", mode="before")
    @classmethod
    def _filter_score_objects(cls, value: JSONValue) -> JSONValue:
        """Keep only dictionary entries when rubric scores arrive as a JSON list.

        Args:
            value: Raw scores field value.

        Returns:
            Tuple of score dictionary items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value


class NextActionPayload(MemoryStewardReadinessPayload):
    """Validated Memory Steward next-action fields."""

    priority: int | None = None
    code: str | None = None
    tool: str | None = None
    summary: str | None = None
    dry_run_first: bool | None = None


class ReadinessSummaryPayload(MemoryStewardReadinessPayload):
    """Validated readiness summary fields used by compact refresh."""

    ready: bool | None = None
    status: str | None = None
    project: JSONValue | None = None
    rag: Annotated[
        RagStatusPayload, Field(description="RAG for this readiness summary payload.")
    ] = RagStatusPayload()
    current_memory_compact: Annotated[
        CurrentCompactPayload,
        Field(description="Current memory compact for this readiness summary payload."),
    ] = CurrentCompactPayload()
    current_memory_compact_review: CurrentCompactReviewPayload | None = None
    warnings: Annotated[
        tuple[str, ...],
        Field(description="Warnings for this readiness summary payload."),
    ] = ()
    next_actions: Annotated[
        tuple[NextActionPayload, ...],
        Field(description="Next actions for this readiness summary payload."),
    ] = ()

    @field_validator("warnings", mode="before")
    @classmethod
    def _filter_warning_strings(cls, value: JSONValue) -> JSONValue:
        """Keep only string entries when warnings arrive as a JSON list.

        Args:
            value: Raw warnings field value.

        Returns:
            Tuple of string warning items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value

    @field_validator("next_actions", mode="before")
    @classmethod
    def _filter_next_action_objects(cls, value: JSONValue) -> JSONValue:
        """Keep only dictionary entries when next_actions arrive as a JSON list.

        Args:
            value: Raw next_actions field value.

        Returns:
            Tuple of next-action dictionary items, or the original value if not a list.
        """
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value


class CompactSourceRefPayload(MemoryStewardReadinessPayload):
    """Validated Memory Compact source reference fields."""

    source_type: str
    source_id: str
    title: str
    detail_path: str
    source_hash: str | None = None


class CompactRefreshDraftPayload(MemoryStewardReadinessPayload):
    """Validated compact refresh draft fields."""

    project: str | None = None
    covered_from: str
    covered_to: str
    status: str
    markdown_body: str
    source_refs: Annotated[
        tuple[CompactSourceRefPayload, ...],
        Field(description="Source refs for this compact refresh draft payload."),
    ] = ()


class ReadinessToolOutputPayload(MemoryStewardReadinessPayload):
    """Output schema for the Memory Steward readiness MCP tool."""

    ready: bool
    status: str
    project: str | None = None
    rag: RagStatusPayload
    current_memory_compact: CurrentCompactPayload
    current_memory_compact_review: CurrentCompactReviewPayload | None = None
    warnings: Annotated[
        tuple[str, ...],
        Field(description="Warnings for this readiness tool output payload."),
    ] = ()
    next_actions: Annotated[
        tuple[NextActionPayload, ...],
        Field(description="Next actions for this readiness tool output payload."),
    ] = ()


class RefreshCurrentCompactOutputPayload(MemoryStewardReadinessPayload):
    """Output schema for the Memory Steward compact refresh MCP tool."""

    status: str
    apply: bool
    force: bool
    refresh_required: bool
    blocked_reasons: Annotated[
        tuple[str, ...],
        Field(
            description="Blocked reasons for this refresh current compact output payload."
        ),
    ] = ()
    blocked_next_actions: Annotated[
        tuple[NextActionPayload, ...],
        Field(
            description="Blocked next actions for this refresh current compact output payload."
        ),
    ] = ()
    readiness: ReadinessToolOutputPayload
    compact_draft: CompactRefreshDraftPayload
    created: JSONValue | None = None
    post_refresh_readiness: ReadinessToolOutputPayload
