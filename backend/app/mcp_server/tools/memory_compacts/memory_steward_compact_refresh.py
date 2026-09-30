"""Compact refresh draft construction for Memory Steward readiness tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.mcp_server.type_validate.memory.memory_steward_readiness_schemas import (
    CompactRefreshDraftPayload,
    CompactSourceRefPayload,
    NextActionPayload,
    ReadinessSummaryPayload,
)
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.shared.types.extra_types import JSONValue


def utc_now_text() -> str:
    """Return current UTC time formatted for JSON payloads.

    Returns:
        ISO-8601 UTC timestamp ending in Z.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def refresh_compact_payload(
    project: str | None,
    readiness: ReadinessSummaryPayload,
    covered_to: str,
    source_refs: Sequence[CompactSourceRefPayload] | None = None,
    semantic_template: Mapping[str, str] | str | None = None,
    final_markdown: str | None = None,
) -> CompactRefreshDraftPayload:
    """Build a validated CURRENT compact refresh draft.

    Args:
        project: Optional project filter for the compact.
        readiness: Validated readiness evidence.
        covered_to: Coverage end timestamp.
        source_refs: Optional project-specific source references.
        semantic_template: Optional section content supplied by the project.
        final_markdown: Optional final agent-edited body.

    Returns:
        Validated compact refresh draft.
    """
    previous_id = readiness.current_memory_compact.id
    previous_updated_at = readiness.current_memory_compact.updated_at
    covered_from = previous_updated_at if previous_updated_at else covered_to
    selected_source_refs = tuple(
        source_refs
        if source_refs is not None
        else refresh_source_refs(previous_id=previous_id, covered_to=covered_to)
    )
    markdown_body = (
        final_markdown
        if final_markdown is not None
        else refresh_markdown_body(
            project=project,
            readiness=readiness,
            covered_from=covered_from,
            covered_to=covered_to,
            source_refs=selected_source_refs,
            semantic_template=semantic_template,
        )
    )
    return CompactRefreshDraftPayload(
        project=project,
        covered_from=covered_from,
        covered_to=covered_to,
        status=MemoryCompactStatus.CURRENT.value,
        markdown_body=markdown_body,
        source_refs=selected_source_refs,
    )


def refresh_source_refs(
    previous_id: JSONValue | None,
    covered_to: str,
) -> list[CompactSourceRefPayload]:
    """Build source references for a compact refresh draft.

    Args:
        previous_id: Optional previous CURRENT compact id.
        covered_to: Coverage end timestamp.

    Returns:
        Validated source reference payloads.
    """
    refs: list[CompactSourceRefPayload] = [
        CompactSourceRefPayload(
            source_type="memory_steward_readiness",
            source_id=f"readiness-refresh-{covered_to}",
            title="Memory Steward readiness refresh evidence",
            detail_path="/memory/contexts/rag/status + /memory/compacts/current",
        )
    ]
    if isinstance(previous_id, str) and previous_id:
        refs.insert(
            0,
            CompactSourceRefPayload(
                source_type="memory_compact",
                source_id=previous_id,
                title="Previous CURRENT Memory Compact",
                detail_path=f"/memory/compacts/{previous_id}",
            ),
        )
    return refs


def refresh_markdown_body(
    project: str | None,
    readiness: ReadinessSummaryPayload,
    covered_from: JSONValue,
    covered_to: str,
    source_refs: Sequence[CompactSourceRefPayload] | None = None,
    semantic_template: Mapping[str, str] | str | None = None,
) -> str:
    """Build markdown body for a CURRENT compact refresh.

    Args:
        project: Optional project filter for the compact.
        readiness: Validated readiness evidence.
        covered_from: Coverage start timestamp or JSON value.
        covered_to: Coverage end timestamp.
        source_refs: Source references whose facts may be cited.
        semantic_template: Optional project-specific section content.

    Returns:
        Markdown body for the refresh compact.
    """
    if isinstance(semantic_template, str):
        return semantic_template
    project_text = project or "default"
    warning_text = ", ".join(readiness.warnings) if readiness.warnings else "none"
    action_lines = next_action_markdown_lines(readiness.next_actions)
    compact = readiness.current_memory_compact
    rag = readiness.rag
    selected_source_refs = tuple(source_refs or ())
    template_sections = {
        key.lower().replace(" ", "_"): value
        for key, value in (semantic_template or {}).items()
    }
    durable_decisions = template_sections.get(
        "durable_decisions",
        "- Decisions must be grounded in the supplied source references.",
    )
    current_state = template_sections.get(
        "current_state",
        "- Current readiness evidence is recorded below for review.",
    )
    risks_blockers = template_sections.get(
        "risks_blockers",
        "- Source freshness and unresolved blockers remain review gates.",
    )
    next_actions = template_sections.get(
        "next_actions",
        "\n".join(action_lines),
    )
    return "\n".join(
        [
            "# Current Memory Compact Draft",
            "",
            "## Durable Decisions",
            durable_decisions,
            "",
            "## Current State",
            current_state,
            f"- Readiness status from the owning service: `{readiness.status}`",
            f"- Project scope: `{project_text}`",
            f"- RAG FTS: `{rag.fts}`",
            f"- RAG vector: `{rag.vector}`",
            f"- RAG embedding: `{rag.embedding}`",
            f"- Previous compact id from the owning service: `{compact.id}`",
            f"- Previous compact updated_at from the owning service: `{compact.updated_at}`",
            f"- Previous compact age_days from the owning service: `{compact.age_days}`",
            "",
            "## Risks and Blockers",
            risks_blockers,
            f"- Active readiness warnings from the owning service: `{warning_text}`",
            "",
            "## Next Actions",
            next_actions,
            "",
            "## Coverage",
            f"- covered_from: `{covered_from}`",
            f"- covered_to: `{covered_to}`",
            f"- project: `{project_text}`",
            "",
            "## Evidence Summary",
            *evidence_summary_lines(list(selected_source_refs)),
            "",
        ]
    )


def evidence_summary_lines(
    source_refs: list[CompactSourceRefPayload],
) -> list[str]:
    """Render source-ref-linked evidence summary lines.

    Args:
        source_refs: Source refs that will be attached to the refresh compact.

    Returns:
        Evidence Summary markdown lines that mention source ids, titles, and paths.
    """
    return [
        (
            f"- `{source_ref.source_id}` — {source_ref.title}; "
            f"detail_path: `{source_ref.detail_path}`."
        )
        for source_ref in source_refs
    ]


def next_action_markdown_lines(
    next_actions: tuple[NextActionPayload, ...],
) -> list[str]:
    """Render next actions as compact markdown bullet lines.

    Args:
        next_actions: Validated next action payloads.

    Returns:
        Markdown bullet lines.
    """
    if not next_actions:
        return ["- No immediate Memory Steward actions required."]
    return [
        (
            "- "
            f"`P{action.priority}` `{action.code}` via "
            f"`{action.tool}` — {action.summary}"
        )
        for action in next_actions
    ]
