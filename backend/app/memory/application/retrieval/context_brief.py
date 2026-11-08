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

from collections.abc import Sequence

from app.memory.application.retrieval.context_brief_markdown import (
    BudgetedMarkdown,
    append_frame,
    delivery_order,
    parse_sections,
    truncate_to_bytes,
)
from app.memory.application.retrieval.context_pack import (
    evidence_references,
    select_pack_matches,
)
from app.memory.application.retrieval.context_retrieval_metadata import (
    retrieval_metadata,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import (
    ContextBriefDeliveryStatus,
    ContextBriefOmissionReason,
)
from app.memory.domain.types.context_payload_types import (
    MAX_CONTEXT_BRIEF_BYTES,
    MAX_CONTEXTS_PER_BRIEF,
    ContextBriefAlreadyDeliveredPayload,
    ContextBriefEntryPayload,
    ContextBriefOmissionPayload,
    ContextBriefPayload,
    ContextBriefSectionPayload,
    ContextRefetchReferencePayload,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextBriefBudgetError,
)
from app.shared.serialization.orjson_codec import dumps_json

# Backstop cap over the whole serialized response (body + refs + omission
# metadata). Transparency records are never silently dropped to fit, so a
# payload that would exceed this cap fails with a typed budget error.
MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES = 262_144


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
    selected = select_pack_matches(matches)
    render = BudgetedMarkdown(byte_budget)
    entries: list[ContextBriefEntryPayload] = []
    already_delivered: list[ContextBriefAlreadyDeliveredPayload] = []
    omitted: list[ContextBriefOmissionPayload] = []

    append_frame(render, "# Alexandria Context Brief")
    append_frame(render, "")
    append_frame(render, f"Query: {truncate_to_bytes(query, 500)}")

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
            omitted.append(
                ContextBriefOmissionPayload(
                    context_id=context_id,
                    reason=ContextBriefOmissionReason.RECORD_BUDGET,
                    heading=None,
                    refetch=refetch,
                )
            )
            continue
        delivery_status = (
            ContextBriefDeliveryStatus.CHANGED
            if previous_hash is not None
            else ContextBriefDeliveryStatus.NEW
        )
        if not entries:
            append_frame(render, "")
            append_frame(render, "## Entries")
        entry = _build_entry(
            render,
            entry_number=len(entries) + 1,
            match=match,
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
        record["reason"]
        in (
            ContextBriefOmissionReason.BYTE_BUDGET,
            ContextBriefOmissionReason.RECORD_BUDGET,
        )
        for record in payload["omitted"]
    )
    if undelivered and not payload["entries"]:
        raise MemoryContextBriefBudgetError(
            "Context brief budget cannot deliver any entry: "
            f"byte_budget={payload['byte_budget']} "
            f"record_budget={payload['record_budget']}"
        )
    serialized_bytes = len(dumps_json(payload))
    if serialized_bytes > MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES:
        raise MemoryContextBriefBudgetError(
            "Context brief serialized payload exceeds the total cap: "
            f"{serialized_bytes} > {MAX_CONTEXT_BRIEF_TOTAL_SERIALIZATION_BYTES} bytes"
        )


def _build_entry(
    render: BudgetedMarkdown,
    *,
    entry_number: int,
    match: ContextSearchMatch,
    delivery_status: ContextBriefDeliveryStatus,
    refetch: ContextRefetchReferencePayload,
    omitted: list[ContextBriefOmissionPayload],
) -> ContextBriefEntryPayload | None:
    """Render one brief entry under the byte budget.

    Args:
        render: Budgeted renderer shared by the whole brief.
        entry_number: One-based delivery position of this entry.
        match: Retrieved match feeding this entry.
        delivery_status: Whether this entry is new or changed.
        refetch: Re-fetch reference for this entry.
        omitted: Omission sink shared by the whole brief.

    Returns:
        Delivered entry payload, or None when even the header cannot fit.
    """
    heading = f"### {entry_number}. {truncate_to_bytes(match.context.title, 200)}"
    header_lines = [
        heading,
        f"- context_id: {match.context.id}",
        f"- delivery_status: {delivery_status}",
        f"- content_hash: {match.chunk.content_hash}",
        f"- score: {match.score:.4f}",
    ]
    if not render.fits_all([*header_lines, ""]):
        omitted.append(
            ContextBriefOmissionPayload(
                context_id=match.context.id,
                reason=ContextBriefOmissionReason.BYTE_BUDGET,
                heading=None,
                refetch=refetch,
            )
        )
        return None
    for line in header_lines:
        render.append(line)
    render.append("")

    delivered_sections: list[ContextBriefSectionPayload] = []
    for section in delivery_order(parse_sections(match.chunk.content)):
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
        truncated_text = truncate_to_bytes(section.text, room)
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
            omitted.append(
                ContextBriefOmissionPayload(
                    context_id=match.context.id,
                    reason=ContextBriefOmissionReason.SECTION_TRUNCATED,
                    heading=section.heading or None,
                    refetch=refetch,
                )
            )
        else:
            omitted.append(
                ContextBriefOmissionPayload(
                    context_id=match.context.id,
                    reason=ContextBriefOmissionReason.BYTE_BUDGET,
                    heading=section.heading or None,
                    refetch=refetch,
                )
            )
    return ContextBriefEntryPayload(
        context_id=match.context.id,
        title=match.context.title,
        score=match.score,
        content_hash=match.chunk.content_hash,
        delivery_status=delivery_status,
        sections=delivered_sections,
    )


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
        evidence_refs=evidence_references([match]),
    )


def _append_transparency_sections(
    render: BudgetedMarkdown,
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
        append_frame(render, "")
        append_frame(render, "## Already Delivered")
        for marker in already_delivered:
            refetch = marker["refetch"]
            append_frame(
                render,
                (
                    f"- context_id: {marker['context_id']} "
                    f"content_hash: {marker['content_hash']} "
                    f"status: unchanged since last delivery; re-fetch: "
                    f"query={refetch['query']} "
                    f"strategy={refetch['retrieval_strategy'].value} "
                    f"chunk_id={refetch['chunk_id'] or 'none'}"
                ),
            )
    if omitted:
        append_frame(render, "")
        append_frame(render, "## Omitted")
        for record in omitted:
            refetch = record["refetch"]
            heading = record["heading"] or "none"
            evidence = ",".join(refetch["evidence_refs"]) or "none"
            append_frame(
                render,
                (
                    f"- context_id: {record['context_id']} reason: {record['reason']} "
                    f"section: {heading}; re-fetch: query={refetch['query']} "
                    f"strategy={refetch['retrieval_strategy'].value} "
                    f"context_id={refetch['context_id']} "
                    f"chunk_id={refetch['chunk_id'] or 'none'} "
                    f"evidence_refs={evidence}"
                ),
            )
