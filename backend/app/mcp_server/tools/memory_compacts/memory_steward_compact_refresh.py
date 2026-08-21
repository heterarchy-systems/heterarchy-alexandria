"""Compact refresh draft construction for Memory Steward readiness tools."""

from __future__ import annotations

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
) -> CompactRefreshDraftPayload:
    """Build a validated CURRENT compact refresh draft.

    Args:
        project: Optional project filter for the compact.
        readiness: Validated readiness evidence.
        covered_to: Coverage end timestamp.

    Returns:
        Validated compact refresh draft.
    """
    previous_id = readiness.current_memory_compact.id
    previous_updated_at = readiness.current_memory_compact.updated_at
    covered_from = previous_updated_at if previous_updated_at else covered_to
    return CompactRefreshDraftPayload(
        project=project,
        covered_from=covered_from,
        covered_to=covered_to,
        status=MemoryCompactStatus.CURRENT.value,
        markdown_body=refresh_markdown_body(
            project=project,
            readiness=readiness,
            covered_from=covered_from,
            covered_to=covered_to,
        ),
        source_refs=tuple(
            refresh_source_refs(previous_id=previous_id, covered_to=covered_to)
        ),
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
            source_type="librarian_readiness",
            source_id=f"readiness-refresh-{covered_to}",
            title="Memory Steward readiness refresh evidence",
            detail_path=(
                "/memory/contexts/rag/status + /memory/compacts/current"
                " + /obsidian/librarian/review-queue"
            ),
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
) -> str:
    """Build markdown body for a CURRENT compact refresh.

    Args:
        project: Optional project filter for the compact.
        readiness: Validated readiness evidence.
        covered_from: Coverage start timestamp or JSON value.
        covered_to: Coverage end timestamp.

    Returns:
        Markdown body for the refresh compact.
    """
    project_text = project or "default"
    warning_text = ", ".join(readiness.warnings) if readiness.warnings else "none"
    action_lines = next_action_markdown_lines(readiness.next_actions)
    compact = readiness.current_memory_compact
    queue = readiness.review_queue
    rag = readiness.rag
    source_refs = refresh_source_refs(previous_id=compact.id, covered_to=covered_to)
    return "\n".join(
        [
            "# heterarchy-alexandria Current Memory Compact — Librarian Refresh",
            "",
            "## Durable Decisions",
            "- Obsidian Markdown remains the durable source of truth.",
            "- RAG/index readiness gates must pass before trusting refreshed memory.",
            "- Vault review queues are handled through safe plan/apply workflows.",
            "",
            "## Current State",
            f"- Project: `{project_text}`",
            f"- Readiness status: `{readiness.status}`",
            f"- Warnings: `{warning_text}`",
            f"- RAG FTS: `{rag.fts}`",
            f"- RAG vector: `{rag.vector}`",
            f"- RAG embedding: `{rag.embedding}`",
            f"- Review queue total: `{queue.total_count()}`",
            (
                "- Review queue auto-move candidates: "
                f"`{queue.auto_move_candidate_count()}`"
            ),
            (
                "- Review queue manual review required: "
                f"`{queue.manual_required_count()}`"
            ),
            f"- Previous compact id: `{compact.id}`",
            f"- Previous compact updated_at: `{compact.updated_at}`",
            f"- Previous compact age_days: `{compact.age_days}`",
            "",
            "## Risks and Blockers",
            (
                f"- Active warnings: `{warning_text}`"
                if readiness.warnings
                else "- No active readiness warnings."
            ),
            "- Treat stale or missing compact state as needs-attention until refreshed.",
            "",
            "## Next Actions",
            *action_lines,
            "",
            "## Coverage",
            f"- covered_from: `{covered_from}`",
            f"- covered_to: `{covered_to}`",
            f"- project: `{project_text}`",
            "",
            "## Evidence Summary",
            *evidence_summary_lines(source_refs),
            "",
            "## Operating Guidance",
            "- Bridge Codex/Hermes to the Obsidian-first second brain.",
            "- Run Memory Steward readiness before claiming the library is operational.",
            "- Refresh this compact when readiness reports stale/missing compact state.",
            "- Prefer safe move plans and report-backed apply flows for vault changes.",
            "- Continue validating backend changes with `cd backend && make ci`.",
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
        return ["- No immediate librarian actions required."]
    return [
        (
            "- "
            f"`P{action.priority}` `{action.code}` via "
            f"`{action.tool}` — {action.summary}"
        )
        for action in next_actions
    ]
