"""Pydantic contracts and policy helpers for Memory Steward readiness tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import ConfigDict, field_validator

from app.shared.schemas.common_schemas import StrictSchemaModel, described_field
from app.shared.types.extra_types import JSONObject, JSONValue


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
        tuple[str, ...], described_field("Warnings for this RAG status payload.")
    ] = ()

    @field_validator("warnings", mode="before")
    @classmethod
    def _filter_warning_strings(cls, value: JSONValue) -> JSONValue:
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
        tuple[str, ...], described_field("Warnings for this current compact payload.")
    ] = ()
    source_refs: Annotated[
        tuple[CurrentCompactSourceRefPayload, ...],
        described_field("Source refs for this current compact payload."),
    ] = ()

    @field_validator("warnings", mode="before")
    @classmethod
    def _filter_warning_strings(cls, value: JSONValue) -> JSONValue:
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value

    @field_validator("source_refs", mode="before")
    @classmethod
    def _filter_source_ref_objects(cls, value: JSONValue) -> JSONValue:
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
        described_field("Reasons for this current compact review score payload."),
    ] = ()

    @field_validator("reasons", mode="before")
    @classmethod
    def _filter_reason_strings(cls, value: JSONValue) -> JSONValue:
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
        described_field("Scores for this current compact review payload."),
    ] = ()
    missing_refs: Annotated[
        tuple[str, ...],
        described_field("Missing refs for this current compact review payload."),
    ] = ()
    contradictions: Annotated[
        tuple[str, ...],
        described_field("Contradictions for this current compact review payload."),
    ] = ()
    stale_reasons: Annotated[
        tuple[str, ...],
        described_field("Stale reasons for this current compact review payload."),
    ] = ()
    recommended_actions: Annotated[
        tuple[str, ...],
        described_field("Recommended actions for this current compact review payload."),
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
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value

    @field_validator("scores", mode="before")
    @classmethod
    def _filter_score_objects(cls, value: JSONValue) -> JSONValue:
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value


class ReviewQueueItemPayload(MemoryStewardReadinessPayload):
    """Validated review queue item fields used by readiness."""

    suggested_destination_path: JSONValue | None = None
    requires_human_review: bool | None = None


class ReviewQueuePayload(MemoryStewardReadinessPayload):
    """Validated vault review queue fields used by readiness."""

    total: int | None = None
    items: Annotated[
        tuple[ReviewQueueItemPayload, ...],
        described_field("Items for this review queue payload."),
    ] = ()

    @field_validator("items", mode="before")
    @classmethod
    def _filter_item_objects(cls, value: JSONValue) -> JSONValue:
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value

    def total_count(self) -> int:
        """Return total queue count with item count fallback.

        Returns:
            Queue total from payload or validated item count.
        """
        return self.total if self.total is not None else len(self.items)

    def auto_move_candidate_count(self) -> int:
        """Count safe auto-move candidates.

        Returns:
            Number of queue items with a destination and no manual-review flag.
        """
        return sum(
            1
            for item in self.items
            if item.suggested_destination_path
            and item.requires_human_review is not True
        )

    def manual_required_count(self) -> int:
        """Count queue items requiring human/vault review.

        Returns:
            Number of items whose manual review flag is true.
        """
        return sum(1 for item in self.items if item.requires_human_review is True)

    def object_items(self) -> list[JSONObject]:
        """Return queue items as JSON objects for response payloads.

        Returns:
            Validated item dictionaries.
        """
        return [item.model_dump(mode="json") for item in self.items]


class NextActionPayload(MemoryStewardReadinessPayload):
    """Validated librarian next-action fields."""

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
        RagStatusPayload, described_field("RAG for this readiness summary payload.")
    ] = RagStatusPayload()
    current_memory_compact: Annotated[
        CurrentCompactPayload,
        described_field("Current memory compact for this readiness summary payload."),
    ] = CurrentCompactPayload()
    current_memory_compact_review: CurrentCompactReviewPayload | None = None
    review_queue: Annotated[
        ReviewQueuePayload,
        described_field("Review queue for this readiness summary payload."),
    ] = ReviewQueuePayload()
    warnings: Annotated[
        tuple[str, ...], described_field("Warnings for this readiness summary payload.")
    ] = ()
    next_actions: Annotated[
        tuple[NextActionPayload, ...],
        described_field("Next actions for this readiness summary payload."),
    ] = ()

    @field_validator("warnings", mode="before")
    @classmethod
    def _filter_warning_strings(cls, value: JSONValue) -> JSONValue:
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return value

    @field_validator("next_actions", mode="before")
    @classmethod
    def _filter_next_action_objects(cls, value: JSONValue) -> JSONValue:
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        return value


class CompactSourceRefPayload(MemoryStewardReadinessPayload):
    """Validated Memory Compact source reference fields."""

    source_type: str
    source_id: str
    title: str
    detail_path: str


class CompactRefreshDraftPayload(MemoryStewardReadinessPayload):
    """Validated compact refresh draft fields."""

    project: str | None = None
    covered_from: str
    covered_to: str
    status: str
    markdown_body: str
    source_refs: Annotated[
        tuple[CompactSourceRefPayload, ...],
        described_field("Source refs for this compact refresh draft payload."),
    ] = ()


class ReadinessReviewQueueOutputPayload(MemoryStewardReadinessPayload):
    """Output schema for readiness review queue summary fields."""

    total: int
    auto_move_candidates: int
    manual_review_required: int
    items: Annotated[
        tuple[JSONObject, ...],
        described_field("Items for this readiness review queue output payload."),
    ] = ()


class ReadinessToolOutputPayload(MemoryStewardReadinessPayload):
    """Output schema for the Memory Steward readiness MCP tool."""

    ready: bool
    status: str
    project: str | None = None
    rag: RagStatusPayload
    current_memory_compact: CurrentCompactPayload
    current_memory_compact_review: CurrentCompactReviewPayload | None = None
    review_queue: ReadinessReviewQueueOutputPayload
    warnings: Annotated[
        tuple[str, ...],
        described_field("Warnings for this readiness tool output payload."),
    ] = ()
    next_actions: Annotated[
        tuple[NextActionPayload, ...],
        described_field("Next actions for this readiness tool output payload."),
    ] = ()


class RefreshCurrentCompactOutputPayload(MemoryStewardReadinessPayload):
    """Output schema for the librarian compact refresh MCP tool."""

    status: str
    apply: bool
    force: bool
    refresh_required: bool
    blocked_reasons: Annotated[
        tuple[str, ...],
        described_field(
            "Blocked reasons for this refresh current compact output payload."
        ),
    ] = ()
    blocked_next_actions: Annotated[
        tuple[NextActionPayload, ...],
        described_field(
            "Blocked next actions for this refresh current compact output payload."
        ),
    ] = ()
    readiness: ReadinessToolOutputPayload
    compact_draft: CompactRefreshDraftPayload
    created: JSONValue | None = None
    post_refresh_readiness: ReadinessToolOutputPayload
