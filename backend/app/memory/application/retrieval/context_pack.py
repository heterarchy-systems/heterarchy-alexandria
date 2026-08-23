"""Context Pack builder for agent-facing RAG responses."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.application.retrieval.context_retrieval_metadata import (
    canonical_context_id,
    retrieval_metadata,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import (
    ContextScope,
    ContextStorageStatus,
)
from app.shared.types.extra_types import JSONValue

MAX_CONTEXTS_PER_PACK = 10
MAX_CONTEXT_PACK_CHARACTERS = 20_000

_PROJECT_SCOPES = frozenset({ContextScope.GLOBAL, ContextScope.PROJECT})
_AGENT_SCOPES = frozenset({ContextScope.AGENT, ContextScope.USER})
_SECTION_HEADINGS = (
    "Project Context",
    "Agent Context",
    "Session Context",
)
_PACK_LIFECYCLE_STATUSES = frozenset({"active", "current"})


def build_context_pack(query: str, matches: list[ContextSearchMatch]) -> str:
    """Build a compact Markdown context pack from retrieval matches.

    Args:
        query: Search query text.
        matches: Retrieved context matches.

    Returns:
        Markdown Context Pack for agent prompts.
    """
    selected_matches = _select_pack_matches(matches)
    sections: dict[str, list[ContextSearchMatch]] = {
        heading: [] for heading in _SECTION_HEADINGS
    }
    for match in selected_matches:
        sections[_section_for_scope(match.context.scope)].append(match)

    evidence_references = _evidence_references(selected_matches)
    empty_content = {match.context.id: "" for match in selected_matches}
    base_pack = _render_context_pack(
        query=query,
        sections=sections,
        evidence_references=evidence_references,
        content_by_context=empty_content,
    )
    while evidence_references and len(base_pack) > MAX_CONTEXT_PACK_CHARACTERS:
        evidence_references.pop()
        base_pack = _render_context_pack(
            query=query,
            sections=sections,
            evidence_references=evidence_references,
            content_by_context=empty_content,
        )
    content_budget = max(0, MAX_CONTEXT_PACK_CHARACTERS - len(base_pack))
    content_by_context = _allocate_content_budget(selected_matches, content_budget)
    context_pack = _render_context_pack(
        query=query,
        sections=sections,
        evidence_references=evidence_references,
        content_by_context=content_by_context,
    )
    return context_pack[:MAX_CONTEXT_PACK_CHARACTERS]


def _select_pack_matches(
    matches: list[ContextSearchMatch],
) -> list[ContextSearchMatch]:
    """Execute select pack matches.

    Args:
        matches: Matches used by this operation.

    Returns:
        list[ContextSearchMatch] result produced by select pack matches.
    """
    recall_statuses = frozenset(ContextStorageStatus.default_recall_values())
    best_by_context: dict[str, ContextSearchMatch] = {}
    for match in matches:
        context = match.context
        lifecycle_status = context.context_metadata.get("lifecycle_status")
        if (
            context.is_archived
            or context.status.value not in recall_statuses
            or (
                isinstance(lifecycle_status, str)
                and lifecycle_status.lower() not in _PACK_LIFECYCLE_STATUSES
            )
        ):
            continue
        context_key = canonical_context_id(context)
        existing = best_by_context.get(context_key)
        if existing is None or match.score > existing.score:
            best_by_context[context_key] = match
    return sorted(
        best_by_context.values(),
        key=lambda match: match.score,
        reverse=True,
    )[:MAX_CONTEXTS_PER_PACK]


def _section_for_scope(scope: ContextScope) -> str:
    """Execute section for scope.

    Args:
        scope: Scope used by this operation.

    Returns:
        str result produced by section for scope.
    """
    if scope in _PROJECT_SCOPES:
        return "Project Context"
    if scope in _AGENT_SCOPES:
        return "Agent Context"
    return "Session Context"


def _render_context_pack(
    query: str,
    sections: dict[str, list[ContextSearchMatch]],
    evidence_references: list[str],
    content_by_context: dict[str, str],
) -> str:
    """Render context pack.

    Args:
        query: Query used by this operation.
        sections: Sections used by this operation.
        evidence_references: Evidence references used by this operation.
        content_by_context: Content by context used by this operation.

    Returns:
        Rendered context pack.
    """
    lines = [
        "# Alexandria Context Pack",
        "",
        f"Query: {_trim_text(query, 500)}",
        "",
    ]
    entry_number = 1
    for section_heading in _SECTION_HEADINGS:
        lines.extend([f"## {section_heading}", ""])
        for match in sections[section_heading]:
            lines.extend(
                _match_lines(
                    entry_number,
                    match,
                    content_by_context[match.context.id],
                )
            )
            entry_number += 1

    lines.extend(["## Evidence References", ""])
    if evidence_references:
        lines.extend(f"- {reference}" for reference in evidence_references)
    else:
        lines.append("- none")
    return "\n".join(lines).strip() + "\n"


def _match_lines(
    entry_number: int,
    match: ContextSearchMatch,
    content: str,
) -> list[str]:
    """Execute match lines.

    Args:
        entry_number: Entry number used by this operation.
        match: Match used by this operation.
        content: Content used by this operation.

    Returns:
        list[str] result produced by match lines.
    """
    context = match.context
    chunk = match.chunk
    heading = f" — {_trim_text(chunk.heading, 160)}" if chunk.heading else ""
    metadata = retrieval_metadata(match)
    lines = [
        f"### {entry_number}. {_trim_text(context.title, 200)}{heading}",
        f"- context_id: {_trim_text(context.id, 200)}",
        f"- kind: {context.kind.value}",
        f"- scope: {context.scope.value}",
        f"- project: {_trim_text(context.project, 200) if context.project else 'none'}",
        f"- agent_id: {_trim_text(context.agent_id, 200) if context.agent_id else 'none'}",
        f"- session_id: {_trim_text(context.session_id, 200) if context.session_id else 'none'}",
        f"- score: {match.score:.4f}",
        f"- canonical_context_id: {_trim_text(metadata.canonical_context_id, 200)}",
        f"- lifecycle_status: {metadata.lifecycle_status.value}",
        f"- retrieval_source: {metadata.retrieval_source}",
        f"- retrieval_strategy: {metadata.retrieval_strategy.value}",
        f"- source_actor_id: {_trim_text(metadata.source_actor_id, 200)}",
        f"- why: {_trim_text(match.why_retrieved, 240)}",
    ]
    if match.graph_evidence:
        lines.append("- graph_evidence:")
        lines.extend(
            "  - "
            f"{item.signal.value}: {item.source_context_id} -[{item.relation}]-> "
            f"{item.target_title} (direction={item.direction.value}, "
            f"distance={item.distance}, evidence={item.evidence_ref})"
            for item in match.graph_evidence
        )
    return [*lines, "", content, ""]


def _allocate_content_budget(
    matches: list[ContextSearchMatch],
    total_budget: int,
) -> dict[str, str]:
    """Execute allocate content budget.

    Args:
        matches: Matches used by this operation.
        total_budget: Total budget used by this operation.

    Returns:
        dict[str, str] result produced by allocate content budget.
    """
    content_by_context: dict[str, str] = {}
    remaining_budget = total_budget
    for index, match in enumerate(matches):
        remaining_contexts = len(matches) - index
        allocation = remaining_budget // remaining_contexts
        content = _trim_text(match.chunk.content.strip(), allocation)
        content_by_context[match.context.id] = content
        remaining_budget -= len(content)
    return content_by_context


def _evidence_references(matches: list[ContextSearchMatch]) -> list[str]:
    """Execute evidence references.

    Args:
        matches: Matches used by this operation.

    Returns:
        list[str] result produced by evidence references.
    """
    references: list[str] = []
    for match in matches:
        metadata = match.context.context_metadata
        references.extend(_reference_values(metadata.get("artifact_refs")))
        references.extend(_reference_values(metadata.get("evidence_refs")))
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            references.extend(_reference_values(provenance.get("artifact_refs")))
            references.extend(_reference_values(provenance.get("evidence_refs")))
        references.extend(item.evidence_ref for item in match.graph_evidence)
    return list(dict.fromkeys(_trim_text(reference, 300) for reference in references))[
        :20
    ]


def _reference_values(value: JSONValue | None) -> list[str]:
    """Execute reference values.

    Args:
        value: Value being processed.

    Returns:
        list[str] result produced by reference values.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _trim_text(value: str, limit: int) -> str:
    """Execute trim text.

    Args:
        value: Value being processed.
        limit: Maximum number of items to process or return.

    Returns:
        str result produced by trim text.
    """
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    return f"{value[: limit - 1]}…"
