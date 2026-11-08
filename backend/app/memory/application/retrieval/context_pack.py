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
    selected_matches = select_pack_matches(matches)
    sections: dict[str, list[ContextSearchMatch]] = {
        heading: [] for heading in _SECTION_HEADINGS
    }
    for match in selected_matches:
        sections[_ContextPackRenderer.section_for_scope(match.context.scope)].append(
            match
        )

    references = evidence_references(selected_matches)
    empty_content = {match.context.id: "" for match in selected_matches}
    base_pack = _ContextPackRenderer.render_context_pack(
        query=query,
        sections=sections,
        evidence_references=references,
        content_by_context=empty_content,
    )
    while references and len(base_pack) > MAX_CONTEXT_PACK_CHARACTERS:
        references.pop()
        base_pack = _ContextPackRenderer.render_context_pack(
            query=query,
            sections=sections,
            evidence_references=references,
            content_by_context=empty_content,
        )
    content_budget = max(0, MAX_CONTEXT_PACK_CHARACTERS - len(base_pack))
    content_by_context = _ContextPackRenderer.allocate_content_budget(
        selected_matches, content_budget
    )
    context_pack = _ContextPackRenderer.render_context_pack(
        query=query,
        sections=sections,
        evidence_references=references,
        content_by_context=content_by_context,
    )
    return context_pack[:MAX_CONTEXT_PACK_CHARACTERS]


def select_pack_matches(
    matches: list[ContextSearchMatch],
) -> list[ContextSearchMatch]:
    """Deduplicate active retrieval matches by canonical context and rank by score.

    Args:
        matches: Candidate context search matches.

    Returns:
        Up to MAX_CONTEXTS_PER_PACK highest-scoring eligible matches.
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


def evidence_references(matches: list[ContextSearchMatch]) -> list[str]:
    """Collect deduplicated artifact, provenance, and graph evidence references.

    Args:
        matches: Selected context search matches.

    Returns:
        Up to 20 deduplicated and length-bounded evidence reference strings.
    """
    references: list[str] = []
    for match in matches:
        metadata = match.context.context_metadata
        references.extend(
            _ContextPackRenderer.reference_values(metadata.get("artifact_refs"))
        )
        references.extend(
            _ContextPackRenderer.reference_values(metadata.get("evidence_refs"))
        )
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            references.extend(
                _ContextPackRenderer.reference_values(provenance.get("artifact_refs"))
            )
            references.extend(
                _ContextPackRenderer.reference_values(provenance.get("evidence_refs"))
            )
        references.extend(item.evidence_ref for item in match.graph_evidence)
    return list(
        dict.fromkeys(
            _ContextPackRenderer.trim_text(reference, 300) for reference in references
        )
    )[:20]


class _ContextPackRenderer:
    """Budget and render Markdown sections and entries for Context Packs."""

    @staticmethod
    def section_for_scope(scope: ContextScope) -> str:
        """Return the Context Pack section heading for a context scope.

        Args:
            scope: Context visibility scope.

        Returns:
            Section heading corresponding to the scope.
        """
        if scope in _PROJECT_SCOPES:
            return "Project Context"
        if scope in _AGENT_SCOPES:
            return "Agent Context"
        return "Session Context"

    @staticmethod
    def render_context_pack(
        query: str,
        sections: dict[str, list[ContextSearchMatch]],
        evidence_references: list[str],
        content_by_context: dict[str, str],
    ) -> str:
        """Render the full Markdown Context Pack from grouped matches and budgets.

        Args:
            query: Search query text.
            sections: Matches grouped by section heading.
            evidence_references: Deduplicated evidence reference strings.
            content_by_context: Budgeted chunk content keyed by context identifier.

        Returns:
            Rendered Markdown Context Pack string.
        """
        lines = [
            "# Alexandria Context Pack",
            "",
            f"Query: {_ContextPackRenderer.trim_text(query, 500)}",
            "",
        ]
        entry_number = 1
        for section_heading in _SECTION_HEADINGS:
            lines.extend([f"## {section_heading}", ""])
            for match in sections[section_heading]:
                lines.extend(
                    _ContextPackRenderer.match_lines(
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

    @staticmethod
    def match_lines(
        entry_number: int,
        match: ContextSearchMatch,
        content: str,
    ) -> list[str]:
        """Format one Context Pack entry header, provenance lines, and body.

        Args:
            entry_number: One-based entry ordinal in the rendered pack.
            match: Retrieved context search match.
            content: Budgeted content string for the match.

        Returns:
            Markdown lines representing the entry.
        """
        context = match.context
        chunk = match.chunk
        heading = (
            f" — {_ContextPackRenderer.trim_text(chunk.heading, 160)}"
            if chunk.heading
            else ""
        )
        metadata = retrieval_metadata(match)
        trim = _ContextPackRenderer.trim_text
        lines = [
            f"### {entry_number}. {trim(context.title, 200)}{heading}",
            f"- context_id: {trim(context.id, 200)}",
            f"- kind: {context.kind.value}",
            f"- scope: {context.scope.value}",
            f"- project: {trim(context.project, 200) if context.project else 'none'}",
            f"- agent_id: {trim(context.agent_id, 200) if context.agent_id else 'none'}",
            f"- session_id: {trim(context.session_id, 200) if context.session_id else 'none'}",
            f"- score: {match.score:.4f}",
            f"- canonical_context_id: {trim(metadata.canonical_context_id, 200)}",
            f"- lifecycle_status: {metadata.lifecycle_status.value}",
            f"- retrieval_source: {metadata.retrieval_source}",
            f"- retrieval_strategy: {metadata.retrieval_strategy.value}",
            f"- source_actor_id: {trim(metadata.source_actor_id, 200)}",
            f"- why: {trim(match.why_retrieved, 240)}",
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

    @staticmethod
    def allocate_content_budget(
        matches: list[ContextSearchMatch],
        total_budget: int,
    ) -> dict[str, str]:
        """Distribute remaining character budget across selected matches.

        Args:
            matches: Selected context search matches.
            total_budget: Total character budget available for match content.

        Returns:
            Mapping from context identifier to trimmed chunk content.
        """
        content_by_context: dict[str, str] = {}
        remaining_budget = total_budget
        for index, match in enumerate(matches):
            remaining_contexts = len(matches) - index
            allocation = remaining_budget // remaining_contexts
            content = _ContextPackRenderer.trim_text(
                match.chunk.content.strip(), allocation
            )
            content_by_context[match.context.id] = content
            remaining_budget -= len(content)
        return content_by_context

    @staticmethod
    def reference_values(value: JSONValue | None) -> list[str]:
        """Extract non-empty string items from a metadata reference sequence.

        Args:
            value: Raw metadata field value.

        Returns:
            List of non-empty string references.
        """
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]

    @staticmethod
    def trim_text(value: str, limit: int) -> str:
        """Truncate text to at most limit characters with an ellipsis suffix.

        Args:
            value: Input string to bound.
            limit: Maximum character length.

        Returns:
            Original or truncated string within the character limit.
        """
        if limit <= 0:
            return ""
        if len(value) <= limit:
            return value
        if limit == 1:
            return "…"
        return f"{value[: limit - 1]}…"
