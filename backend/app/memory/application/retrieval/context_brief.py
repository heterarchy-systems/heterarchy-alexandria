"""Budgeted model-delivery brief with repetition suppression over Context Packs.

``build_context_brief`` derives a delivery brief from the same retrieval
matches that feed :func:`app.memory.application.retrieval.context_pack.build_context_pack`;
it never runs retrieval itself. Budget accounting is exact utf-8 byte
accounting; the optional token figure is a labeled rough estimate.

Self-amplification guard: the builder takes ``list[ContextSearchMatch]`` as
input and emits a structurally different ``ContextBriefPayload`` that carries
no identity of its own (no id, no embedded Context payload). Brief output
therefore cannot re-enter retrieval as evidence, brief-derived content has no
``context_id`` of its own, and repeated brief generation cannot grow the pack.

Transparency: unlike the evidence-ref trim loop in ``context_pack.py`` (which
silently drops references), every entry or section that is omitted or
truncated here is reported in the ``omitted`` list together with the exact
re-fetch reference needed to retrieve it through the existing retrieval API.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from app.memory.application.retrieval.context_pack import (
    MAX_CONTEXT_PACK_CHARACTERS,
    MAX_CONTEXTS_PER_PACK,
    _evidence_references,
    _select_pack_matches,
)
from app.memory.application.retrieval.context_retrieval_metadata import (
    retrieval_metadata,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.types.context_payload_types import (
    ContextBriefAlreadyDeliveredPayload,
    ContextBriefDeliveryStatus,
    ContextBriefEntryPayload,
    ContextBriefOmissionPayload,
    ContextBriefOmissionReason,
    ContextBriefPayload,
    ContextBriefSectionPayload,
    ContextRefetchReferencePayload,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextBriefBudgetError,
)
from app.shared.serialization.orjson_codec import dumps_json
from app.shared.types.extra_types import JSONValue

MAX_CONTEXT_BRIEF_BYTES = MAX_CONTEXT_PACK_CHARACTERS
MAX_CONTEXTS_PER_BRIEF = MAX_CONTEXTS_PER_PACK
# Backstop cap over the whole serialized response (body + refs + omission
# metadata). Transparency records are never silently dropped to fit, so a
# payload that would exceed this cap fails with a typed budget error.
MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES = 262_144

_SECTION_HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$")

_CORE_SECTION_RANKS: tuple[tuple[str, ...], ...] = (
    ("goal",),
    ("constraint",),
    ("unconfirmed", "unverified", "uncertain"),
    ("next action", "next single action", "next step"),
)


@dataclass(frozen=True, slots=True)
class _BriefSection:
    """One HANDOFF-style markdown section parsed from chunk content."""

    heading: str
    text: str


class _BudgetedMarkdown:
    """Byte-exact line accumulator that enforces the brief byte budget."""

    def __init__(self, byte_budget: int) -> None:
        """Initialize the accumulator.

        Args:
            byte_budget: Maximum rendered utf-8 byte count.
        """
        self._lines: list[str] = []
        self._joined_bytes = 0
        self._byte_budget = byte_budget

    def remaining(self) -> int:
        """Return the unspent byte budget.

        Returns:
            Budget bytes not yet consumed by the rendered lines.
        """
        return self._byte_budget - self._joined_bytes

    def append_overhead(self) -> int:
        """Return the joining-newline cost of the next appended line.

        Returns:
            One byte when the render already has lines, otherwise zero.
        """
        return 1 if self._lines else 0

    def fits(self, text: str) -> bool:
        """Return whether one appended line would stay within budget.

        Args:
            text: Candidate line to append.

        Returns:
            Whether appending the line keeps the render within budget.
        """
        return self._cost(text) <= self.remaining()

    def fits_all(self, lines: Sequence[str]) -> bool:
        """Return whether a block of appended lines would stay within budget.

        Args:
            lines: Candidate lines appended together.

        Returns:
            Whether appending all lines keeps the render within budget.
        """
        if not lines:
            return True
        cost = sum(self._cost(line) for line in lines)
        if not self._lines:
            cost -= 1
        return cost <= self.remaining()

    def append(self, text: str) -> None:
        """Append one line to the render.

        Args:
            text: Line to append; callers must check ``fits`` first.
        """
        self._joined_bytes += self._cost(text)
        self._lines.append(text)

    def render(self) -> str:
        """Return the rendered markdown.

        Returns:
            Rendered brief text within the byte budget.
        """
        return "\n".join(self._lines)

    def _cost(self, text: str) -> int:
        """Return the byte cost of appending one line.

        Args:
            text: Candidate line to append.

        Returns:
            Utf-8 byte count including the joining newline when non-empty.
        """
        return len(text.encode("utf-8")) + self.append_overhead()


def build_context_brief(
    query: str,
    matches: list[ContextSearchMatch],
    *,
    byte_budget: int = MAX_CONTEXT_BRIEF_BYTES,
    record_budget: int = MAX_CONTEXTS_PER_BRIEF,
    previously_delivered: Sequence[tuple[str, str]] = (),
) -> ContextBriefPayload:
    """Build a budgeted model-delivery brief from retrieval matches.

    Selection reuses the Context Pack canonical dedupe and best-score
    ordering. Entries whose ``(context_id, content_hash)`` pair was already
    delivered are suppressed into compact ``already_delivered`` markers;
    entries whose hash changed are delivered again marked as ``changed``.
    Core HANDOFF sections (goal, constraints, unconfirmed status, next
    actions) are delivered first per entry; truncated sections are labeled
    and never silently dropped.

    Args:
        query: Search query text shared with the retrieval call site.
        matches: Retrieved context matches feeding the brief.
        byte_budget: Maximum rendered utf-8 byte count.
        record_budget: Maximum number of delivered context entries.
        previously_delivered: ``(context_id, content_hash)`` pairs delivered
            to the same consumer by earlier briefs.

    Returns:
        Identity-free brief payload with exact byte accounting.

    Raises:
        ValueError: If either budget is negative.
        MemoryContextBriefBudgetError: When no candidate entry can be
            delivered within the budgets, or when the total serialized
            payload (body + refs + omission metadata) would exceed
            ``MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES``.
    """
    if byte_budget < 0 or record_budget < 0:
        raise ValueError("brief budgets must be non-negative")
    delivered_hashes = dict(previously_delivered)
    selected = _select_pack_matches(matches)
    render = _BudgetedMarkdown(byte_budget)
    entries: list[ContextBriefEntryPayload] = []
    already_delivered: list[ContextBriefAlreadyDeliveredPayload] = []
    omitted: list[ContextBriefOmissionPayload] = []

    _append_frame(render, "# Alexandria Context Brief")
    _append_frame(render, "")
    _append_frame(render, f"Query: {_truncate_to_bytes(query, 500)}")

    delivered_count = 0
    for match in selected:
        refetch = _refetch_reference(match, query)
        context_id = match.context.id
        content_hash = match.chunk.content_hash
        previous_hash = delivered_hashes.get(context_id)
        if previous_hash == content_hash:
            marker = ContextBriefAlreadyDeliveredPayload(
                context_id=context_id,
                content_hash=content_hash,
                refetch=refetch,
            )
            already_delivered.append(marker)
            continue
        if delivered_count >= record_budget:
            _record_omission(
                omitted,
                context_id=context_id,
                reason="record_budget",
                heading=None,
                refetch=refetch,
            )
            continue
        delivery_status: ContextBriefDeliveryStatus = (
            "changed" if previous_hash is not None else "new"
        )
        if not entries:
            _append_frame(render, "")
            _append_frame(render, "## Entries")
        entry = _build_entry(
            render,
            entry_number=len(entries) + 1,
            match=match,
            query=query,
            delivery_status=delivery_status,
            refetch=refetch,
            omitted=omitted,
        )
        if entry is None:
            continue
        entries.append(entry)
        delivered_count += 1

    _append_transparency_sections(render, already_delivered, omitted)
    brief_text = render.render()
    payload = ContextBriefPayload(
        query=query,
        byte_budget=byte_budget,
        record_budget=record_budget,
        total_bytes=len(brief_text.encode("utf-8")),
        estimated_tokens=len(brief_text) // 4,
        entries=entries,
        already_delivered=already_delivered,
        omitted=omitted,
        context_brief=brief_text,
    )
    _enforce_budget_contract(payload)
    return payload


def _enforce_budget_contract(payload: ContextBriefPayload) -> None:
    """Fail closed when the rendered brief violates the delivery contract.

    A request whose budget cannot deliver any candidate entry is a typed
    budget error, never an empty success; suppressed unchanged entries and
    absent matches stay legitimate empty deliveries. The total serialized
    response (body + refs + omission metadata) must also stay within the
    hard serialization cap.

    Args:
        payload: Fully rendered brief payload.

    Raises:
        MemoryContextBriefBudgetError: When no candidate entry fit the
            budgets or the serialized payload exceeds the total cap.
    """
    undelivered = any(
        record["reason"] in ("byte_budget", "record_budget")
        for record in payload["omitted"]
    )
    if undelivered and not payload["entries"]:
        raise MemoryContextBriefBudgetError(
            "Context brief budget cannot deliver any entry: "
            f"byte_budget={payload['byte_budget']} "
            f"record_budget={payload['record_budget']}"
        )
    serialized_bytes = len(dumps_json(_payload_as_json(payload)))
    if serialized_bytes > MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES:
        raise MemoryContextBriefBudgetError(
            "Context brief serialized payload exceeds the total cap: "
            f"{serialized_bytes} > {MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES} bytes"
        )


def _payload_as_json(payload: ContextBriefPayload) -> JSONValue:
    """Project one brief payload onto plain JSON for exact size accounting.

    Args:
        payload: Fully rendered brief payload.

    Returns:
        JSON-compatible payload with identical serialization shape.
    """
    return cast(
        JSONValue,
        {
            "query": payload["query"],
            "byte_budget": payload["byte_budget"],
            "record_budget": payload["record_budget"],
            "total_bytes": payload["total_bytes"],
            "estimated_tokens": payload["estimated_tokens"],
            "entries": [dict(entry) for entry in payload["entries"]],
            "already_delivered": [
                dict(marker) for marker in payload["already_delivered"]
            ],
            "omitted": [dict(record) for record in payload["omitted"]],
            "context_brief": payload["context_brief"],
        },
    )


def _build_entry(
    render: _BudgetedMarkdown,
    entry_number: int,
    match: ContextSearchMatch,
    query: str,
    delivery_status: ContextBriefDeliveryStatus,
    refetch: ContextRefetchReferencePayload,
    omitted: list[ContextBriefOmissionPayload],
) -> ContextBriefEntryPayload | None:
    """Render one brief entry under the byte budget.

    Args:
        render: Budgeted renderer shared by the whole brief.
        entry_number: One-based delivery position of this entry.
        match: Retrieved match feeding this entry.
        query: Query text used for re-fetch references.
        delivery_status: Whether this entry is new or changed.
        refetch: Re-fetch reference for this entry.
        omitted: Omission sink shared by the whole brief.

    Returns:
        Delivered entry payload, or None when even the header cannot fit.
    """
    heading = f"### {entry_number}. {_truncate_to_bytes(match.context.title, 200)}"
    header_lines = [
        heading,
        f"- context_id: {match.context.id}",
        f"- delivery_status: {delivery_status}",
        f"- content_hash: {match.chunk.content_hash}",
        f"- score: {match.score:.4f}",
    ]
    if not render.fits_all([*header_lines, ""]):
        _record_omission(
            omitted,
            context_id=match.context.id,
            reason="byte_budget",
            heading=None,
            refetch=refetch,
        )
        return None
    for line in header_lines:
        render.append(line)
    render.append("")

    delivered_sections: list[ContextBriefSectionPayload] = []
    for section in _delivery_order(_parse_sections(match.chunk.content)):
        if not section.heading and not section.text:
            continue
        frame = f"#### {section.heading}\n" if section.heading else ""
        if render.fits(frame + section.text):
            render.append(frame + section.text)
            delivered_sections.append(
                ContextBriefSectionPayload(
                    heading=section.heading,
                    text=section.text,
                    truncated=False,
                    delivered_bytes=len(section.text.encode("utf-8")),
                )
            )
            continue
        room = (
            render.remaining() - render.append_overhead() - len(frame.encode("utf-8"))
        )
        truncated_text = _truncate_to_bytes(section.text, room)
        if truncated_text:
            render.append(frame + truncated_text)
            delivered_sections.append(
                ContextBriefSectionPayload(
                    heading=section.heading,
                    text=truncated_text,
                    truncated=True,
                    delivered_bytes=len(truncated_text.encode("utf-8")),
                )
            )
            _record_omission(
                omitted,
                context_id=match.context.id,
                reason="section_truncated",
                heading=section.heading or None,
                refetch=refetch,
            )
        else:
            _record_omission(
                omitted,
                context_id=match.context.id,
                reason="byte_budget",
                heading=section.heading or None,
                refetch=refetch,
            )
    return ContextBriefEntryPayload(
        context_id=match.context.id,
        title=match.context.title,
        score=match.score,
        content_hash=match.chunk.content_hash,
        delivery_status=delivery_status,
        sections=delivered_sections,
    )


def _parse_sections(content: str) -> list[_BriefSection]:
    """Parse chunk content into HANDOFF-style markdown sections.

    Args:
        content: Chunk content to parse.

    Returns:
        Sections in source order; unheaded content becomes one section.
    """
    sections: list[_BriefSection] = []
    heading = ""
    body_lines: list[str] = []
    for line in content.splitlines():
        matched = _SECTION_HEADING_PATTERN.match(line)
        if matched is None:
            body_lines.append(line)
            continue
        text = "\n".join(body_lines).strip()
        if heading or text:
            sections.append(_BriefSection(heading=heading, text=text))
        heading = matched.group(1)
        body_lines = []
    text = "\n".join(body_lines).strip()
    if heading or text:
        sections.append(_BriefSection(heading=heading, text=text))
    return sections


def _delivery_order(sections: list[_BriefSection]) -> list[_BriefSection]:
    """Order sections core-first while preserving source order otherwise.

    Args:
        sections: Parsed sections in source order.

    Returns:
        Sections ordered goal, constraints, unconfirmed, next actions, then
        the remaining sections in source order.
    """
    ranked = [
        (_core_rank(section.heading), index, section)
        for index, section in enumerate(sections)
    ]
    ranked.sort(key=lambda item: (item[0] is None, item[0] or 0, item[1]))
    return [section for _, _, section in ranked]


def _core_rank(heading: str) -> int | None:
    """Return the core-priority rank of one section heading.

    Args:
        heading: Section heading to classify.

    Returns:
        Core rank, or None when the section is supplementary.
    """
    normalized = heading.strip().lower()
    for rank, tokens in enumerate(_CORE_SECTION_RANKS):
        if any(token in normalized for token in tokens):
            return rank
    return None


def _refetch_reference(
    match: ContextSearchMatch,
    query: str,
) -> ContextRefetchReferencePayload:
    """Build the exact re-fetch reference for one match.

    Args:
        match: Retrieved match to reference.
        query: Query text that retrieved this match.

    Returns:
        Re-fetch reference reusing the pack's evidence-ref fields.
    """
    metadata = retrieval_metadata(match)
    return ContextRefetchReferencePayload(
        context_id=match.context.id,
        canonical_context_id=metadata.canonical_context_id,
        query=query,
        retrieval_strategy=metadata.retrieval_strategy,
        chunk_id=match.chunk.id,
        evidence_refs=_evidence_references([match]),
    )


def _record_omission(
    omitted: list[ContextBriefOmissionPayload],
    *,
    context_id: str,
    reason: ContextBriefOmissionReason,
    heading: str | None,
    refetch: ContextRefetchReferencePayload,
) -> None:
    """Record one omission for the brief transparency sections.

    Args:
        omitted: Omission sink shared by the whole brief.
        context_id: Source context identifier of the omitted item.
        reason: Why the item is not delivered in full.
        heading: Section heading when the omission is section-scoped.
        refetch: Exact re-fetch reference for the omitted item.
    """
    omitted.append(
        ContextBriefOmissionPayload(
            context_id=context_id,
            reason=reason,
            heading=heading,
            refetch=refetch,
        )
    )


def _append_transparency_sections(
    render: _BudgetedMarkdown,
    already_delivered: list[ContextBriefAlreadyDeliveredPayload],
    omitted: list[ContextBriefOmissionPayload],
) -> None:
    """Render the already-delivered and omitted transparency sections.

    Args:
        render: Budgeted renderer shared by the whole brief.
        already_delivered: Suppressed unchanged entries.
        omitted: Omitted or truncated items.
    """
    if already_delivered:
        _append_frame(render, "")
        _append_frame(render, "## Already Delivered")
        for marker in already_delivered:
            _append_frame(render, _marker_line(marker))
    if omitted:
        _append_frame(render, "")
        _append_frame(render, "## Omitted")
        for record in omitted:
            _append_frame(render, _omission_line(record))


def _append_frame(render: _BudgetedMarkdown, text: str) -> None:
    """Append one structural line, truncating it when the budget is tight.

    Args:
        render: Budgeted renderer shared by the whole brief.
        text: Structural line to append.
    """
    if render.fits(text):
        render.append(text)
        return
    rendered = _truncate_to_bytes(text, render.remaining())
    if rendered:
        render.append(rendered)


def _marker_line(marker: ContextBriefAlreadyDeliveredPayload) -> str:
    """Render one already-delivered marker line.

    Args:
        marker: Suppressed unchanged entry.

    Returns:
        Compact marker line with its re-fetch reference.
    """
    refetch = marker["refetch"]
    return (
        f"- context_id: {marker['context_id']} "
        f"content_hash: {marker['content_hash']} "
        f"status: unchanged since last delivery; re-fetch: "
        f"query={refetch['query']} strategy={refetch['retrieval_strategy'].value} "
        f"chunk_id={refetch['chunk_id'] or 'none'}"
    )


def _omission_line(record: ContextBriefOmissionPayload) -> str:
    """Render one omission transparency line.

    Args:
        record: Omitted or truncated item.

    Returns:
        Omission line with its exact re-fetch reference.
    """
    refetch = record["refetch"]
    heading = record["heading"] or "none"
    evidence = ",".join(refetch["evidence_refs"]) or "none"
    return (
        f"- context_id: {record['context_id']} reason: {record['reason']} "
        f"section: {heading}; re-fetch: query={refetch['query']} "
        f"strategy={refetch['retrieval_strategy'].value} "
        f"context_id={refetch['context_id']} "
        f"chunk_id={refetch['chunk_id'] or 'none'} "
        f"evidence_refs={evidence}"
    )


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """Return the longest utf-8-safe prefix of one text.

    Args:
        text: Text to truncate.
        max_bytes: Maximum utf-8 byte count of the prefix.

    Returns:
        Longest prefix within the byte limit; empty when the limit is not
        positive.
    """
    if max_bytes <= 0:
        return ""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    low = 0
    high = len(text)
    while low < high:
        midpoint = (low + high + 1) // 2
        if len(text[:midpoint].encode("utf-8")) <= max_bytes:
            low = midpoint
        else:
            high = midpoint - 1
    return text[:low]
