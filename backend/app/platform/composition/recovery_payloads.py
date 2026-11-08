"""Typed mappings for operational recovery callback results."""

from __future__ import annotations

from typing_extensions import TypedDict

from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionOperationError,
    ObsidianGraphProjectionRebuildReport,
)
from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
    ObsidianGraphIssueDetail,
    ObsidianGraphIssueListResult,
)
from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionIssueCount,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class RecoveryEmbeddingBatchPayload(TypedDict, closed=True):
    """One resumable Context embedding batch result."""

    scanned: int
    updated: int
    skipped: int
    warnings: list[str]


class RecoveryEmbeddingPayload(TypedDict, closed=True):
    """One complete Context embedding recovery result."""

    scanned: int
    updated: int
    skipped: int
    warnings: list[str]
    batches: list[JSONObject]
    batch_size: int
    max_batches: int


class RecoveryDeadLetterOutcomePayload(TypedDict, closed=True):
    """One item receipt included in a dead-letter recovery summary."""

    status: str
    effect_identity: str


class RecoveryDeadLetterEntryPayload(TypedDict, closed=True):
    """One reconciled dead-letter entry in the readiness response."""

    entry_id: str
    ready: bool
    outcomes: list[JSONObject]


class RecoveryDeadLetterPayload(TypedDict, closed=True):
    """Bounded dead-letter recovery readiness payload."""

    enabled: bool
    ready: bool
    entries: list[JSONObject]
    truncated: bool


class RecoveryCurrentCompactPayload(TypedDict, closed=True):
    """Status of the CURRENT source used for existing memory."""

    project: str | None
    available: bool
    compact_id: str | None
    status: str
    scope: str


class RecoveryGraphOperationErrorPayload(TypedDict, closed=True):
    """Graph rebuild operation error with its complete nullable source identity."""

    code: str
    relative_path: str | None
    note_id: str | None
    edge_id: str | None
    detail: str | None


class RecoveryGraphIssueCountPayload(TypedDict, closed=True):
    """Count for one graph projection source issue."""

    code: str
    count: int


class RecoveryGraphRebuildPayload(TypedDict, closed=True):
    """Complete graph projection rebuild report in JSON field order."""

    status: str
    graph_read_model: str
    run_id: str
    scanned: int
    indexed: int
    updated: int
    skipped: int
    duration_seconds: float
    issue_total: int
    issue_counts: list[JSONObject]
    issues: list[JSONObject]
    issues_truncated: bool
    errors: list[JSONObject]


class RecoveryGraphIssueDetailPayload(TypedDict, closed=True):
    """One source-index issue with every nullable detail preserved."""

    issue_id: str
    code: str
    edge_id: str
    source_note_id: str
    source_path: str
    source_title: str | None
    target_path: str
    relation: str
    detail: str | None
    projection_run_id: str | None


class RecoveryGraphIssueListPayload(TypedDict, closed=True):
    """Complete graph issue list page and pagination state."""

    issues: list[JSONObject]
    next_cursor: str | None
    run_id: str | None


class RecoveryPayloadMapper:
    """Serialize graph DTOs in the original Pydantic JSON-mode field order."""

    @staticmethod
    def _wire_float(value: int | float) -> float:
        """Normalize JSON-mode numeric output while preserving the stored value."""
        if isinstance(value, int):
            return float(value)
        return float.__float__(value)

    @staticmethod
    def graph_operation_error(
        error: ObsidianGraphProjectionOperationError,
    ) -> RecoveryGraphOperationErrorPayload:
        """Map one operation error to its complete JSON payload."""
        return RecoveryGraphOperationErrorPayload(
            code=str.__str__(error.code),
            relative_path=(
                None
                if error.relative_path is None
                else str.__str__(error.relative_path)
            ),
            note_id=(None if error.note_id is None else str.__str__(error.note_id)),
            edge_id=(None if error.edge_id is None else str.__str__(error.edge_id)),
            detail=(None if error.detail is None else str.__str__(error.detail)),
        )

    @staticmethod
    def graph_issue_count(
        issue_count: ObsidianGraphProjectionIssueCount,
    ) -> RecoveryGraphIssueCountPayload:
        """Map one diagnostic code and count in the report field order."""
        return RecoveryGraphIssueCountPayload(
            code=str.__str__(issue_count.code.value),
            count=int.__int__(issue_count.count),
        )

    @staticmethod
    def graph_rebuild(
        report: ObsidianGraphProjectionRebuildReport,
    ) -> JSONObject:
        """Return the full rebuild report using JSON-mode scalar conversions."""
        payload = RecoveryGraphRebuildPayload(
            status=str.__str__(report.status),
            graph_read_model=str.__str__(report.graph_read_model),
            run_id=str.__str__(report.run_id),
            scanned=int.__int__(report.scanned),
            indexed=int.__int__(report.indexed),
            updated=int.__int__(report.updated),
            skipped=int.__int__(report.skipped),
            duration_seconds=RecoveryPayloadMapper._wire_float(report.duration_seconds),
            issue_total=int.__int__(report.issue_total),
            issue_counts=[
                dict[str, JSONValue](
                    **RecoveryPayloadMapper.graph_issue_count(issue_count)
                )
                for issue_count in report.issue_counts
            ],
            issues=[
                dict[str, JSONValue](
                    **RecoveryPayloadMapper.graph_operation_error(issue)
                )
                for issue in report.issues
            ],
            issues_truncated=report.issues_truncated,
            errors=[
                dict[str, JSONValue](
                    **RecoveryPayloadMapper.graph_operation_error(error)
                )
                for error in report.errors
            ],
        )
        return dict[str, JSONValue](**payload)

    @staticmethod
    def graph_issue_detail(
        issue: ObsidianGraphIssueDetail,
    ) -> RecoveryGraphIssueDetailPayload:
        """Map one graph issue preserving JSON-compatible string values."""
        return RecoveryGraphIssueDetailPayload(
            issue_id=str.__str__(issue.issue_id),
            code=str.__str__(issue.code),
            edge_id=str.__str__(issue.edge_id),
            source_note_id=str.__str__(issue.source_note_id),
            source_path=str.__str__(issue.source_path),
            source_title=(
                None if issue.source_title is None else str.__str__(issue.source_title)
            ),
            target_path=str.__str__(issue.target_path),
            relation=str.__str__(issue.relation),
            detail=(None if issue.detail is None else str.__str__(issue.detail)),
            projection_run_id=(
                None
                if issue.projection_run_id is None
                else str.__str__(issue.projection_run_id)
            ),
        )

    @staticmethod
    def graph_issue_list(result: ObsidianGraphIssueListResult) -> JSONObject:
        """Map an issue page while preserving its source order and nulls."""
        payload = RecoveryGraphIssueListPayload(
            issues=[
                dict[str, JSONValue](**RecoveryPayloadMapper.graph_issue_detail(issue))
                for issue in result.issues
            ],
            next_cursor=(
                None if result.next_cursor is None else str.__str__(result.next_cursor)
            ),
            run_id=(None if result.run_id is None else str.__str__(result.run_id)),
        )
        return dict[str, JSONValue](**payload)
