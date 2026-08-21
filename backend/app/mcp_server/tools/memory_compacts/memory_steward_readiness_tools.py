"""Memory Steward HTTP adapters for readiness and compact refresh."""

from __future__ import annotations

from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiError
from app.mcp_server.tools.memory_compacts.memory_compact_tools import (
    alexandria_create_memory_compact,
    alexandria_review_memory_compact,
)
from app.mcp_server.tools.memory_compacts.memory_steward_compact_refresh import (
    refresh_compact_payload,
    utc_now_text,
)
from app.mcp_server.type_validate.memory.memory_steward_readiness_parsers import (
    parse_current_compact,
    parse_rag_status,
    parse_readiness_summary,
    parse_review_queue,
    result_object,
    source_ref_dicts,
)
from app.mcp_server.type_validate.memory.memory_steward_readiness_policy import (
    needs_current_compact_refresh,
    rag_health_blocking_warnings,
    readiness_next_actions,
    readiness_warnings,
    review_blocking_warnings,
)
from app.mcp_server.type_validate.memory.memory_steward_readiness_schemas import (
    CurrentCompactPayload,
    CurrentCompactReviewPayload,
    NextActionPayload,
    RagStatusPayload,
    ReadinessReviewQueueOutputPayload,
    ReadinessToolOutputPayload,
    RefreshCurrentCompactOutputPayload,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.shared.type_validation.strict_json_value import model_validate_json_value
from app.shared.types.extra_types import JSONObject, JSONValue


async def alexandria_memory_steward_readiness(
    client: AlexandriaApiClient,
    project: str | None = None,
    max_compact_age_days: int = 30,
) -> JSONValue:
    """Return one Memory Steward readiness summary.

    Args:
        client: Backend HTTP client.
        project: Optional project filter for current compact and review queue.
        max_compact_age_days: Maximum acceptable age for the current compact.

    Returns:
        Readiness summary composed from RAG health, current Memory Compact, and
        vault review queue state.
    """
    try:
        rag_status = await client.get("/memory/contexts/rag/status")
    except AlexandriaApiError as exc:
        return _rag_status_unavailable_readiness(
            project=project,
            max_compact_age_days=max_compact_age_days,
            error_message=str(exc),
        )
    compact_query: JSONObject | None = None if project is None else {"project": project}
    current_compact = await client.get("/memory/compacts/current", params=compact_query)
    review_payload: JSONObject = {"limit": 20}
    if project is not None:
        review_payload["project"] = project
    review_queue_payload = await client.post(
        "/obsidian/librarian/review-queue", review_payload
    )

    rag = parse_rag_status(rag_status)
    compact = parse_current_compact(current_compact)
    compact_review = await _current_compact_review(client, compact)
    review_queue = parse_review_queue(review_queue_payload)
    review_total = review_queue.total_count()
    auto_move_candidates = review_queue.auto_move_candidate_count()
    manual_review_required = review_queue.manual_required_count()
    compact_age_days = compact.calculated_age_days()
    bounded_max_age_days = max(int(max_compact_age_days), 1)
    warnings = readiness_warnings(
        rag=rag,
        compact=compact,
        compact_age_days=compact_age_days,
        max_compact_age_days=bounded_max_age_days,
        review_total=review_total,
    )
    warnings.extend(_compact_review_warnings(compact_review))
    next_actions = readiness_next_actions(
        warnings=warnings,
        auto_move_candidates=auto_move_candidates,
        manual_review_required=manual_review_required,
        review_total=review_total,
    )
    output = ReadinessToolOutputPayload(
        ready=not warnings,
        status="ready" if not warnings else "needs_attention",
        project=project,
        rag=rag,
        current_memory_compact=compact.model_copy(
            update={
                "age_days": compact_age_days,
                "max_age_days": bounded_max_age_days,
            }
        ),
        current_memory_compact_review=compact_review,
        review_queue=ReadinessReviewQueueOutputPayload(
            total=review_total,
            auto_move_candidates=auto_move_candidates,
            manual_review_required=manual_review_required,
            items=tuple(review_queue.object_items()),
        ),
        warnings=tuple(warnings),
        next_actions=tuple(
            model_validate_json_value(NextActionPayload, action)
            for action in next_actions
        ),
    )
    return output.model_dump(mode="json")


async def _current_compact_review(
    client: AlexandriaApiClient,
    compact: CurrentCompactPayload,
) -> CurrentCompactReviewPayload | None:
    if not isinstance(compact.id, str) or not compact.id:
        return None
    source_observations = _source_observations_from_compact(compact)
    review_payload = await alexandria_review_memory_compact(
        client,
        compact.id,
        source_observations=source_observations,
    )
    return model_validate_json_value(
        CurrentCompactReviewPayload,
        result_object(review_payload),
    )


def _rag_status_unavailable_readiness(
    project: str | None, max_compact_age_days: int, error_message: str
) -> JSONValue:
    warnings = ["rag_status_unavailable"]
    next_actions = readiness_next_actions(
        warnings=warnings,
        auto_move_candidates=0,
        manual_review_required=0,
        review_total=0,
    )
    bounded_max_age_days = max(int(max_compact_age_days), 1)
    output = ReadinessToolOutputPayload(
        ready=False,
        status="needs_attention",
        project=project,
        rag=RagStatusPayload(warnings=(error_message,)),
        current_memory_compact=CurrentCompactPayload(
            project=project,
            max_age_days=bounded_max_age_days,
        ),
        current_memory_compact_review=None,
        review_queue=ReadinessReviewQueueOutputPayload(
            total=0,
            auto_move_candidates=0,
            manual_review_required=0,
            items=(),
        ),
        warnings=tuple(warnings),
        next_actions=tuple(
            model_validate_json_value(NextActionPayload, action)
            for action in next_actions
        ),
    )
    return output.model_dump(mode="json")


def _source_observations_from_compact(
    compact: CurrentCompactPayload,
) -> list[JSONObject]:
    observations: list[JSONObject] = []
    for source_ref in compact.source_refs:
        if not isinstance(source_ref.source_id, str) or not source_ref.source_id:
            continue
        observation: JSONObject = {"source_id": source_ref.source_id}
        if isinstance(source_ref.detail_path, str):
            observation["detail_path"] = source_ref.detail_path
        if isinstance(source_ref.current_source_hash, str):
            observation["current_source_hash"] = source_ref.current_source_hash
        observations.append(observation)
    return observations


def _compact_review_warnings(
    compact_review: CurrentCompactReviewPayload | None,
) -> list[str]:
    if compact_review is None:
        return []
    if compact_review.verdict == "blocked":
        return ["current_memory_compact_review_blocked"]
    if compact_review.verdict == "needs_revision":
        return ["current_memory_compact_review_needs_revision"]
    return []


async def alexandria_memory_steward_refresh_current_compact(
    client: AlexandriaApiClient,
    project: str | None = None,
    max_compact_age_days: int = 30,
    apply: bool = False,
    force: bool = False,
    covered_to: str | None = None,
) -> JSONValue:
    """Plan or apply a CURRENT Memory Compact refresh from readiness evidence.

    Args:
        client: Backend HTTP client.
        project: Optional project filter for the compact.
        max_compact_age_days: Maximum acceptable age for the current compact.
        apply: Create the compact when refresh is required or forced.
        force: Create a compact even when readiness is already fresh.
        covered_to: Optional deterministic coverage end timestamp.

    Returns:
        Refresh plan, optional creation result, and post-refresh readiness.
    """
    readiness_payload = await alexandria_memory_steward_readiness(
        client, project=project, max_compact_age_days=max_compact_age_days
    )
    readiness = parse_readiness_summary(readiness_payload)
    refresh_required = force or needs_current_compact_refresh(readiness.warnings)
    rag_blocked_reasons = rag_health_blocking_warnings(readiness.warnings)
    review_blocked_reasons = review_blocking_warnings(
        readiness.warnings,
        readiness.review_queue.manual_required_count(),
    )
    blocked_reasons = rag_blocked_reasons + review_blocked_reasons
    blocked_next_actions = tuple(
        action
        for action in readiness.next_actions
        if action.code in {"repair_rag_index", "review_manual_vault_queue"}
    )
    refresh_status = "refresh_required" if refresh_required else "up_to_date"
    if refresh_required and rag_blocked_reasons:
        refresh_status = "blocked_by_rag_health"
    elif refresh_required and review_blocked_reasons:
        refresh_status = "blocked_by_vault_review"
    compact_draft = refresh_compact_payload(
        project=project,
        readiness=readiness,
        covered_to=covered_to or utc_now_text(),
    )
    created: JSONValue | None = None
    post_refresh_readiness = model_validate_json_value(
        ReadinessToolOutputPayload,
        result_object(readiness_payload),
    )
    if apply and refresh_required and not blocked_reasons:
        created = await alexandria_create_memory_compact(
            client,
            covered_from=compact_draft.covered_from,
            covered_to=compact_draft.covered_to,
            markdown_body=compact_draft.markdown_body,
            project=project,
            status=MemoryCompactStatus.CURRENT,
            source_refs=source_ref_dicts(compact_draft),
        )
        post_refresh_payload = await alexandria_memory_steward_readiness(
            client, project=project, max_compact_age_days=max_compact_age_days
        )
        post_refresh_readiness = model_validate_json_value(
            ReadinessToolOutputPayload,
            result_object(post_refresh_payload),
        )
        refresh_status = "refreshed"

    output = RefreshCurrentCompactOutputPayload(
        status=refresh_status,
        apply=apply,
        force=force,
        refresh_required=refresh_required,
        blocked_reasons=blocked_reasons,
        blocked_next_actions=blocked_next_actions,
        readiness=model_validate_json_value(
            ReadinessToolOutputPayload,
            result_object(readiness_payload),
        ),
        compact_draft=compact_draft,
        created=created,
        post_refresh_readiness=post_refresh_readiness,
    )
    return output.model_dump(mode="json")
