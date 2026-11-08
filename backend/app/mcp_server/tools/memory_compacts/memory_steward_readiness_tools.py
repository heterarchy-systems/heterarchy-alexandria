"""Memory Steward HTTP adapters for readiness and compact refresh."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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
    CompactSourceRefPayload,
    CurrentCompactPayload,
    CurrentCompactReviewPayload,
    RagStatusPayload,
    ReadinessToolOutputPayload,
    RefreshCurrentCompactOutputPayload,
)
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactRefreshStatus,
    MemoryCompactReviewVerdict,
    MemoryCompactStatus,
    MemoryStewardReadinessWarningCode as _WarnCode,
)
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
        project: Optional project filter for the current compact.
        max_compact_age_days: Maximum acceptable age for the current compact.

    Returns:
        Readiness summary composed from RAG health and the current Memory Compact.
    """
    try:
        rag_status = await client.get("/memory/contexts/rag/status")
    except AlexandriaApiError as exc:
        return _MemoryStewardReadinessHelper.rag_status_unavailable_readiness(
            project=project,
            max_compact_age_days=max_compact_age_days,
            error_message=str(exc),
        )
    compact_query: JSONObject | None = None if project is None else {"project": project}
    current_compact = await client.get("/memory/compacts/current", params=compact_query)

    rag = parse_rag_status(rag_status)
    compact = parse_current_compact(current_compact)
    compact_review = await _MemoryStewardReadinessHelper.current_compact_review(
        client, compact
    )
    compact_age_days = compact.calculated_age_days()
    bounded_max_age_days = max(max_compact_age_days, 1)
    warnings = readiness_warnings(
        rag=rag,
        compact=compact,
        compact_age_days=compact_age_days,
        max_compact_age_days=bounded_max_age_days,
    )
    warnings.extend(
        _MemoryStewardReadinessHelper.compact_review_warnings(compact_review)
    )
    next_actions = readiness_next_actions(warnings=warnings)
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
        warnings=tuple(warnings),
        next_actions=tuple(next_actions),
    )
    return output.model_dump(mode="json")


async def alexandria_memory_steward_refresh_current_compact(
    client: AlexandriaApiClient,
    project: str | None = None,
    max_compact_age_days: int = 30,
    apply: bool = False,
    force: bool = False,
    covered_to: str | None = None,
    draft_only: bool = False,
    source_refs: Sequence[Mapping[str, JSONValue]] | None = None,
    semantic_template: Mapping[str, str] | str | None = None,
    final_markdown: str | None = None,
) -> JSONValue:
    """Plan or apply a CURRENT Memory Compact refresh from readiness evidence.

    Args:
        client: Backend HTTP client.
        project: Optional project filter for the compact.
        max_compact_age_days: Maximum acceptable age for the current compact.
        apply: Create the compact when refresh is required or forced.
        force: Create a compact even when readiness is already fresh.
        covered_to: Optional deterministic coverage end timestamp.
        draft_only: Create a DRAFT for agent semantic editing instead of a
            direct CURRENT promotion; the draft must pass review through
            alexandria_apply_reviewed_memory_compact before promotion.
        source_refs: Optional project-specific source references.
        semantic_template: Optional project-specific section content.
        final_markdown: Optional final agent-edited Markdown body.

    Returns:
        Refresh plan, optional creation result, and post-refresh readiness.
    """
    readiness_payload = await alexandria_memory_steward_readiness(
        client, project=project, max_compact_age_days=max_compact_age_days
    )
    readiness = parse_readiness_summary(readiness_payload)
    refresh_required = force or needs_current_compact_refresh(readiness.warnings)
    rag_blocked_reasons = rag_health_blocking_warnings(readiness.warnings)
    review_blocked_reasons = (
        () if draft_only else review_blocking_warnings(readiness.warnings)
    )
    blocked_reasons = rag_blocked_reasons + review_blocked_reasons
    blocked_next_actions = tuple(
        action for action in readiness.next_actions if action.code == "repair_rag_index"
    )
    refresh_status = (
        MemoryCompactRefreshStatus.REFRESH_REQUIRED.value
        if refresh_required
        else MemoryCompactRefreshStatus.UP_TO_DATE.value
    )
    if refresh_required and rag_blocked_reasons:
        refresh_status = MemoryCompactRefreshStatus.BLOCKED_BY_RAG_HEALTH.value
    elif refresh_required and review_blocked_reasons:
        refresh_status = MemoryCompactRefreshStatus.BLOCKED_BY_COMPACT_REVIEW.value
    compact_draft = refresh_compact_payload(
        project=project,
        readiness=readiness,
        covered_to=covered_to or utc_now_text(),
        source_refs=_MemoryStewardReadinessHelper.validated_source_refs(source_refs),
        semantic_template=semantic_template,
        final_markdown=final_markdown,
    )
    if draft_only:
        compact_draft = compact_draft.model_copy(
            update={"status": MemoryCompactStatus.DRAFT.value}
        )
    created: JSONValue | None = None
    initial_readiness = model_validate_json_value(
        ReadinessToolOutputPayload,
        result_object(readiness_payload),
    )
    post_refresh_readiness = initial_readiness
    if apply and refresh_required and not blocked_reasons:
        created = await alexandria_create_memory_compact(
            client,
            covered_from=compact_draft.covered_from,
            covered_to=compact_draft.covered_to,
            markdown_body=compact_draft.markdown_body,
            project=project,
            status=MemoryCompactStatus.DRAFT
            if draft_only
            else MemoryCompactStatus.CURRENT,
            source_refs=source_ref_dicts(compact_draft),
        )
        if draft_only:
            refresh_status = MemoryCompactRefreshStatus.DRAFT_CREATED.value
        else:
            post_refresh_payload = await alexandria_memory_steward_readiness(
                client, project=project, max_compact_age_days=max_compact_age_days
            )
            post_refresh_readiness = model_validate_json_value(
                ReadinessToolOutputPayload,
                result_object(post_refresh_payload),
            )
            refresh_status = MemoryCompactRefreshStatus.REFRESHED.value

    output = RefreshCurrentCompactOutputPayload(
        status=refresh_status,
        apply=apply,
        force=force,
        refresh_required=refresh_required,
        blocked_reasons=blocked_reasons,
        blocked_next_actions=blocked_next_actions,
        readiness=initial_readiness,
        compact_draft=compact_draft,
        created=created,
        post_refresh_readiness=post_refresh_readiness,
    )
    return output.model_dump(mode="json")


class _MemoryStewardReadinessHelper:
    """Cohesive helpers for Memory Steward readiness evaluation and refresh inputs."""

    @staticmethod
    async def current_compact_review(
        client: AlexandriaApiClient,
        compact: CurrentCompactPayload,
    ) -> CurrentCompactReviewPayload | None:
        """Evaluate the active CURRENT compact against the Memory Steward rubric.

        Args:
            client: Backend HTTP API client.
            compact: Parsed CURRENT compact payload, if one exists.

        Returns:
            Validated compact review payload, or None when no CURRENT compact id exists.
        """
        if not isinstance(compact.id, str) or not compact.id:
            return None
        source_observations = (
            _MemoryStewardReadinessHelper.source_observations_from_compact(compact)
        )
        review_payload = await alexandria_review_memory_compact(
            client,
            compact.id,
            source_observations=source_observations,
        )
        return model_validate_json_value(
            CurrentCompactReviewPayload,
            result_object(review_payload),
        )

    @staticmethod
    def rag_status_unavailable_readiness(
        project: str | None, max_compact_age_days: int, error_message: str
    ) -> JSONValue:
        """Build a degraded readiness summary when the RAG status endpoint fails.

        Args:
            project: Optional project filter for the readiness request.
            max_compact_age_days: Configured maximum compact age in days.
            error_message: Error description from the failed RAG status call.

        Returns:
            Serialized ReadinessToolOutputPayload marking RAG status as unavailable.
        """
        warnings = [_WarnCode.RAG_STATUS_UNAVAILABLE.value]
        next_actions = readiness_next_actions(warnings=warnings)
        bounded_max_age_days = max(max_compact_age_days, 1)
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
            warnings=tuple(warnings),
            next_actions=tuple(next_actions),
        )
        return output.model_dump(mode="json")

    @staticmethod
    def source_observations_from_compact(
        compact: CurrentCompactPayload,
    ) -> list[JSONObject]:
        """Extract source hash observations from a parsed CURRENT compact payload.

        Args:
            compact: Parsed CURRENT compact payload containing source references.

        Returns:
            List of source observation payloads for review verification.
        """
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

    @staticmethod
    def compact_review_warnings(
        compact_review: CurrentCompactReviewPayload | None,
    ) -> list[str]:
        """Map a CURRENT compact review verdict into readiness warning codes.

        Args:
            compact_review: Validated review result for the CURRENT compact, if any.

        Returns:
            List of warning codes when the review is blocked or needs revision.
        """
        if compact_review is None:
            return []
        if compact_review.verdict == MemoryCompactReviewVerdict.BLOCKED:
            return [_WarnCode.CURRENT_MEMORY_COMPACT_REVIEW_BLOCKED.value]
        if compact_review.verdict == MemoryCompactReviewVerdict.NEEDS_REVISION:
            return [_WarnCode.CURRENT_MEMORY_COMPACT_REVIEW_NEEDS_REVISION.value]
        return []

    @staticmethod
    def validated_source_refs(
        source_refs: Sequence[Mapping[str, JSONValue]] | None,
    ) -> tuple[CompactSourceRefPayload, ...] | None:
        """Validate project source references at the MCP boundary.

        Args:
            source_refs: Optional raw source reference mappings.

        Returns:
            Tuple of validated CompactSourceRefPayload instances, or None.
        """
        if source_refs is None:
            return None
        return tuple(
            model_validate_json_value(CompactSourceRefPayload, dict(source_ref))
            for source_ref in source_refs
        )
