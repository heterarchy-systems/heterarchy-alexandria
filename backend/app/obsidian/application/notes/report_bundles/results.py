"""Typed report-bundle errors and immutable operation result construction."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from app.obsidian.application.notes.report_bundles.report_bundle_enums import (
    ReportBundleStage,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianReportBundleRequest,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianNoteWriteResult,
    ObsidianReportBundleGraphResult,
    ObsidianReportBundleResult,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianReportBundleCompletionStatus,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class ReportBundleErrorDict(TypedDict):
    """Closed wire payload for report-bundle warnings and failures."""

    function: str
    message: str
    code: NotRequired[str]
    paths: NotRequired[list[str]]


def operation_error(
    function: str,
    error: Exception | str,
    code: str | None = None,
    paths: list[str] | None = None,
) -> JSONObject:
    """Build one typed public-safe report-bundle error payload.

    Args:
        function: Stable operation or stage name.
        error: Error whose secret-safe message is reported, or a known message.
        code: Optional stable error code to preserve when present.
        paths: Optional ordered paths attached to duplicate evidence.

    Returns:
        JSON-compatible error mapping with the original optional-key presence.
    """
    message = (
        str(error) or type(error).__name__ if isinstance(error, Exception) else error
    )
    payload = ReportBundleErrorDict(function=function, message=message)
    if code is not None:
        payload["code"] = code
    if paths is not None:
        payload["paths"] = paths
    return dict[str, JSONValue](**payload)


def failure(
    request: ObsidianReportBundleRequest,
    status: ObsidianReportBundleCompletionStatus,
    stage: ReportBundleStage,
    error: Exception,
    source: ObsidianNoteWriteResult | None = None,
    owner_writes: tuple[ObsidianNoteWriteResult, ...] = (),
) -> ObsidianReportBundleResult:
    """Build a report-bundle failure result for the owning service.

    Args:
        request: Normalized request that failed.
        status: Completion state selected by the orchestration owner.
        stage: Report-bundle stage at which the failure occurred.
        error: Error details captured for the response or checkpoint.
        source: Source write evidence already observed, when available.
        owner_writes: Owner write evidence already observed.

    Returns:
        Failure result describing the operation and its known evidence.
    """
    return ObsidianReportBundleResult(
        completion_status=status,
        idempotency_key=request.idempotency_key,
        replayed=False,
        source=source,
        owner_writes=owner_writes,
        graph=ObsidianReportBundleGraphResult(
            expected_incoming_edges=len(request.graph_owners),
            verified_incoming_edges=0,
        ),
        failed_stage=stage.value,
        errors=(operation_error(function=stage.value.lower(), error=error),),
    )
