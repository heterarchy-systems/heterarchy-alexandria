"""Canonical Markdown rendering and parsing for resume context packages.

The rendered body satisfies both contract surfaces that guard compact notes:

- the HANDOFF/COMPACT lint contract headings (``Summary``, ``Current State``,
  ``Next Actions``, ``Restore Prompt``), and
- the CURRENT Memory Compact section policy (``Durable Decisions``,
  ``Current State``, ``Risks and Blockers``, ``Next Actions``, ``Coverage``,
  ``Evidence Summary``).

Rendering and parsing are exact inverses over the validated single-line value
space enforced by the assembly service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageAttributedItem,
    ResumePackageEvidenceRef,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryResumePackageValidationError,
)
from app.shared.types.types_convert_utils import aware_utc_datetime

_HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$")

_ITEM_TEXT_PREFIX = "- text: "
_ITEM_SOURCE_PREFIX = "  source_context_id: "
_BULLET_PREFIX = "- "
_KEY_LINE_PATTERN = re.compile(r"^- ([a-z_]+): (.*)$")
_EVIDENCE_KEY_LINE_PATTERN = re.compile(r"^  ([a-z_]+): (.*)$")

_SUMMARY = "Summary"
_GOAL = "Goal"
_ACCEPTED_CHANGES = "Accepted Changes"
_CONSTRAINTS = "Constraints"
_VERIFIED_COMPLETE = "Verified Complete"
_IMPLEMENTED_UNVERIFIED = "Implemented Unverified"
_UNFINISHED_TASKS = "Unfinished Tasks"
_UNCERTAIN_RESULTS = "Uncertain Results"
_BLOCKERS = "Blockers"
_CURRENT_STATE = "Current State"
_DURABLE_DECISIONS = "Durable Decisions"
_RISKS_AND_BLOCKERS = "Risks and Blockers"
_NEXT_ACTIONS = "Next Actions"
_NEXT_SINGLE_ACTION = "Next Single Action"
_RESTORE_PROMPT = "Restore Prompt"
_COVERAGE = "Coverage"
_EVIDENCE_SUMMARY = "Evidence Summary"
_EVIDENCE_REFS = "Evidence Refs"
_LINEAGE = "Lineage"

_SCALAR_SECTIONS: tuple[str, ...] = (
    _SUMMARY,
    _GOAL,
    _CURRENT_STATE,
    _NEXT_SINGLE_ACTION,
    _RESTORE_PROMPT,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedResumePackageBody:
    """Structured fields parsed back from one canonical package body."""

    summary: str
    goal: str
    current_state: str
    next_single_action: str
    restore_prompt: str
    accepted_changes: tuple[ResumePackageAttributedItem, ...]
    constraints: tuple[ResumePackageAttributedItem, ...]
    verified_complete: tuple[str, ...]
    implemented_unverified: tuple[str, ...]
    unfinished_tasks: tuple[str, ...]
    uncertain_results: tuple[str, ...]
    blockers: tuple[str, ...]
    covered_from: datetime
    covered_to: datetime
    evidence_refs: tuple[ResumePackageEvidenceRef, ...]
    lineage_id: str
    worker_id: str | None
    run_id: str | None
    workspace_id: str | None
    session_id: str | None
    previous_package_id: str | None
    package_revision: int
    draft_hash: str
    request_id: str | None = None


def render_resume_package_markdown(
    *,
    project: str | None,
    goal: str,
    summary: str,
    current_state: str,
    next_single_action: str,
    covered_from: datetime,
    covered_to: datetime,
    accepted_changes: tuple[ResumePackageAttributedItem, ...],
    constraints: tuple[ResumePackageAttributedItem, ...],
    verified_complete: tuple[str, ...],
    implemented_unverified: tuple[str, ...],
    unfinished_tasks: tuple[str, ...],
    uncertain_results: tuple[str, ...],
    blockers: tuple[str, ...],
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
    lineage_id: str,
    worker_id: str | None,
    run_id: str | None,
    workspace_id: str | None,
    session_id: str | None,
    previous_package_id: str | None,
    package_revision: int,
    draft_hash: str,
    request_id: str | None = None,
) -> str:
    """Render the canonical linted Markdown body for one resume package.

    Args:
        project: Optional project scope recorded under Coverage.
        goal: Original objective sourced from the caller.
        summary: Single-line package summary.
        current_state: Single-line current-state statement.
        next_single_action: The single next action for the resuming worker.
        covered_from: Inclusive coverage start timestamp.
        covered_to: Coverage end timestamp.
        accepted_changes: Accepted changes with source attribution.
        constraints: Constraints with source attribution.
        verified_complete: Tasks verified complete by observed evidence.
        implemented_unverified: Tasks implemented but not verified.
        unfinished_tasks: Tasks intentionally left unfinished.
        uncertain_results: Results whose confidence is uncertain.
        blockers: Active blockers.
        evidence_refs: Observed evidence references sealed into the package.
        lineage_id: Stable lineage identity for the handoff chain.
        worker_id: Optional originating worker identity.
        run_id: Optional originating run identity.
        workspace_id: Optional workspace reference.
        session_id: Optional session reference.
        previous_package_id: Sealed predecessor package id, when any.
        package_revision: Sealed monotonic revision within the lineage.
        draft_hash: Stable content hash of the caller draft and evidence.
        request_id: Optional caller retry-fencing identity sealed with the
            package.

    Returns:
        Canonical Markdown body honoring the lint and compact contracts.
    """
    lines: list[str] = []
    lines.extend(_scalar_section(_SUMMARY, summary))
    lines.extend(_scalar_section(_GOAL, goal))
    lines.extend(_item_section(_ACCEPTED_CHANGES, accepted_changes))
    lines.extend(_item_section(_CONSTRAINTS, constraints))
    lines.extend(_bullet_section(_VERIFIED_COMPLETE, verified_complete))
    lines.extend(_bullet_section(_IMPLEMENTED_UNVERIFIED, implemented_unverified))
    lines.extend(_bullet_section(_UNFINISHED_TASKS, unfinished_tasks))
    lines.extend(_bullet_section(_UNCERTAIN_RESULTS, uncertain_results))
    lines.extend(_bullet_section(_BLOCKERS, blockers))
    lines.extend(_scalar_section(_CURRENT_STATE, current_state))
    lines.extend(
        _bullet_section(
            _DURABLE_DECISIONS,
            (
                "Accepted changes and constraints above stay durable for this "
                "lineage; each item keeps its evidence attribution."
            ),
        )
    )
    lines.extend(
        _bullet_section(
            _RISKS_AND_BLOCKERS,
            f"{len(blockers)} recorded blockers; see the Blockers section for "
            "the current list.",
        )
    )
    lines.extend(_bullet_section(_NEXT_ACTIONS, next_single_action))
    lines.extend(_scalar_section(_NEXT_SINGLE_ACTION, next_single_action))
    lines.extend(
        _scalar_section(
            _RESTORE_PROMPT,
            _restore_prompt(
                lineage_id=lineage_id,
                package_revision=package_revision,
                next_single_action=next_single_action,
            ),
        )
    )
    lines.extend(
        _key_section(
            _COVERAGE,
            (
                ("covered_from", _isoformat(covered_from)),
                ("covered_to", _isoformat(covered_to)),
                ("project", project if project is not None else "default"),
            ),
        )
    )
    lines.extend(_evidence_summary_section(evidence_refs))
    lines.extend(_evidence_refs_section(evidence_refs))
    lines.extend(
        _key_section(
            _LINEAGE,
            (
                ("lineage_id", lineage_id),
                ("worker_id", worker_id if worker_id is not None else "none"),
                ("run_id", run_id if run_id is not None else "none"),
                ("workspace_id", workspace_id if workspace_id is not None else "none"),
                ("session_id", session_id if session_id is not None else "none"),
                (
                    "previous_package_id",
                    previous_package_id if previous_package_id is not None else "none",
                ),
                ("package_revision", str(package_revision)),
                ("draft_hash", draft_hash),
                ("request_id", request_id if request_id is not None else "none"),
            ),
        )
    )
    return "\n".join(lines) + "\n"


def parse_resume_package_markdown(markdown_body: str) -> ParsedResumePackageBody:
    """Parse one canonical resume package body back into structured fields.

    Args:
        markdown_body: Stored Memory Compact Markdown body.

    Returns:
        Parsed structured package fields.

    Raises:
        MemoryResumePackageValidationError: When the body is not a canonical
            resume package body.
    """
    sections = _sections(markdown_body)
    scalar = {
        heading: _single_scalar_line(sections, heading) for heading in _SCALAR_SECTIONS
    }
    return ParsedResumePackageBody(
        summary=scalar[_SUMMARY],
        goal=scalar[_GOAL],
        current_state=scalar[_CURRENT_STATE],
        next_single_action=scalar[_NEXT_SINGLE_ACTION],
        restore_prompt=scalar[_RESTORE_PROMPT],
        accepted_changes=_parse_items(sections, _ACCEPTED_CHANGES),
        constraints=_parse_items(sections, _CONSTRAINTS),
        verified_complete=_parse_bullets(sections, _VERIFIED_COMPLETE),
        implemented_unverified=_parse_bullets(sections, _IMPLEMENTED_UNVERIFIED),
        unfinished_tasks=_parse_bullets(sections, _UNFINISHED_TASKS),
        uncertain_results=_parse_bullets(sections, _UNCERTAIN_RESULTS),
        blockers=_parse_bullets(sections, _BLOCKERS),
        covered_from=_parse_datetime(_key_value(sections, _COVERAGE, "covered_from")),
        covered_to=_parse_datetime(_key_value(sections, _COVERAGE, "covered_to")),
        evidence_refs=_parse_evidence_refs(sections),
        lineage_id=_key_value(sections, _LINEAGE, "lineage_id"),
        worker_id=_optional_key_value(sections, _LINEAGE, "worker_id"),
        run_id=_optional_key_value(sections, _LINEAGE, "run_id"),
        workspace_id=_optional_key_value(sections, _LINEAGE, "workspace_id"),
        session_id=_optional_key_value(sections, _LINEAGE, "session_id"),
        previous_package_id=_optional_key_value(
            sections, _LINEAGE, "previous_package_id"
        ),
        package_revision=_parse_revision(
            _key_value(sections, _LINEAGE, "package_revision")
        ),
        draft_hash=_key_value(sections, _LINEAGE, "draft_hash"),
        request_id=_optional_lineage_key(sections, "request_id"),
    )


def _sections(markdown_body: str) -> dict[str, tuple[str, ...]]:
    """Split a Markdown body into ``##`` sections.

    Args:
        markdown_body: Canonical package Markdown body.

    Returns:
        Mapping of heading text to content lines.
    """
    parsed: dict[str, tuple[str, ...]] = {}
    current_heading: str | None = None
    for line in markdown_body.splitlines():
        match = _HEADING_PATTERN.match(line)
        if match:
            current_heading = match.group(1).strip()
            parsed.setdefault(current_heading, ())
            continue
        if current_heading is not None:
            parsed[current_heading] = (*parsed[current_heading], line)
    return parsed


def _single_scalar_line(
    sections: dict[str, tuple[str, ...]],
    heading: str,
) -> str:
    """Return the single content line of one scalar section.

    Args:
        sections: Parsed sections by heading.
        heading: Heading text for this section.

    Returns:
        The single scalar line value.

    Raises:
        MemoryResumePackageValidationError: When the section is absent or does
            not contain exactly one non-empty line.
    """
    lines = sections.get(heading)
    if lines is None:
        raise MemoryResumePackageValidationError(
            f"Resume package body missing section: {heading}"
        )
    content = tuple(line for line in lines if line.strip())
    if len(content) != 1:
        raise MemoryResumePackageValidationError(
            f"Resume package section must contain exactly one line: {heading}"
        )
    return content[0]


def _parse_items(
    sections: dict[str, tuple[str, ...]],
    heading: str,
) -> tuple[ResumePackageAttributedItem, ...]:
    """Parse one attributed-item section.

    Args:
        sections: Parsed sections by heading.
        heading: Heading text for this section.

    Returns:
        Attributed items in stored order.

    Raises:
        MemoryResumePackageValidationError: When the canonical item layout is
            violated.
    """
    lines = sections.get(heading, ())
    items: list[ResumePackageAttributedItem] = []
    pending_text: str | None = None
    for line in lines:
        if line.startswith(_ITEM_TEXT_PREFIX):
            if pending_text is not None:
                raise MemoryResumePackageValidationError(
                    f"Resume package item missing source attribution: {heading}"
                )
            pending_text = line[len(_ITEM_TEXT_PREFIX) :]
            continue
        if line.startswith(_ITEM_SOURCE_PREFIX):
            if pending_text is None:
                raise MemoryResumePackageValidationError(
                    f"Resume package item source without text: {heading}"
                )
            items.append(
                ResumePackageAttributedItem(
                    text=pending_text,
                    source_context_id=line[len(_ITEM_SOURCE_PREFIX) :],
                )
            )
            pending_text = None
    if pending_text is not None:
        raise MemoryResumePackageValidationError(
            f"Resume package item missing source attribution: {heading}"
        )
    return tuple(items)


def _parse_bullets(
    sections: dict[str, tuple[str, ...]],
    heading: str,
) -> tuple[str, ...]:
    """Parse one bullet-list section.

    Args:
        sections: Parsed sections by heading.
        heading: Heading text for this section.

    Returns:
        Bullet values in stored order; empty when the section is absent.
    """
    return tuple(
        line[len(_BULLET_PREFIX) :]
        for line in sections.get(heading, ())
        if line.startswith(_BULLET_PREFIX)
    )


def _key_value(
    sections: dict[str, tuple[str, ...]],
    heading: str,
    key: str,
) -> str:
    """Return one required ``- key: value`` entry from a section.

    Args:
        sections: Parsed sections by heading.
        heading: Heading text for this section.
        key: Canonical key name.

    Returns:
        The stored value.

    Raises:
        MemoryResumePackageValidationError: When the key entry is absent.
    """
    lines = sections.get(heading)
    if lines is None:
        raise MemoryResumePackageValidationError(
            f"Resume package body missing section: {heading}"
        )
    for line in lines:
        match = _KEY_LINE_PATTERN.match(line)
        if match is not None and match.group(1) == key:
            return match.group(2)
    raise MemoryResumePackageValidationError(
        f"Resume package section missing key: {heading}/{key}"
    )


def _optional_key_value(
    sections: dict[str, tuple[str, ...]],
    heading: str,
    key: str,
) -> str | None:
    """Return one optional ``- key: value`` entry, mapping ``none`` to None.

    Args:
        sections: Parsed sections by heading.
        heading: Heading text for this section.
        key: Canonical key name.

    Returns:
        The stored value, or None when stored as ``none``.
    """
    value = _key_value(sections, heading, key)
    return None if value == "none" else value


def _optional_lineage_key(
    sections: dict[str, tuple[str, ...]],
    key: str,
) -> str | None:
    """Return one optional lineage key that older bodies may omit entirely.

    Args:
        sections: Parsed sections by heading.
        key: Canonical key name.

    Returns:
        The stored value, None when stored as ``none``, or None when the key
        is absent (bodies sealed before the key existed).
    """
    lines = sections.get(_LINEAGE)
    if lines is None:
        return None
    for line in lines:
        match = _KEY_LINE_PATTERN.match(line)
        if match is not None and match.group(1) == key:
            return None if match.group(2) == "none" else match.group(2)
    return None


def _parse_evidence_refs(
    sections: dict[str, tuple[str, ...]],
) -> tuple[ResumePackageEvidenceRef, ...]:
    """Parse the structured evidence-ref section.

    Args:
        sections: Parsed sections by heading.

    Returns:
        Evidence references in stored order.

    Raises:
        MemoryResumePackageValidationError: When the canonical evidence layout
            is violated.
    """
    lines = sections.get(_EVIDENCE_REFS)
    if lines is None:
        raise MemoryResumePackageValidationError(
            f"Resume package body missing section: {_EVIDENCE_REFS}"
        )
    evidence_refs: list[ResumePackageEvidenceRef] = []
    current_keys: dict[str, str] = {}
    for line in lines:
        if line.startswith("- context_id:"):
            current_keys = {"context_id": line[len("- context_id:") :].lstrip()}
            continue
        if not line.startswith("  "):
            continue
        match = _EVIDENCE_KEY_LINE_PATTERN.match(line)
        if match is None or not current_keys:
            continue
        current_keys[match.group(1)] = match.group(2)
        if match.group(1) == "observed_updated_at":
            evidence_refs.append(_evidence_ref_from_keys(current_keys))
            current_keys = {}
    if current_keys:
        raise MemoryResumePackageValidationError(
            "Resume package evidence ref is incomplete"
        )
    return tuple(evidence_refs)


def _evidence_ref_from_keys(
    keys: dict[str, str],
) -> ResumePackageEvidenceRef:
    """Build one evidence ref from parsed canonical keys.

    Args:
        keys: Canonical evidence keys parsed from one block.

    Returns:
        Typed evidence reference.

    Raises:
        MemoryResumePackageValidationError: When required keys are missing or
            malformed.
    """
    required = (
        "context_id",
        "content_hash",
        "source",
        "created_at",
        "observed_updated_at",
    )
    missing = tuple(key for key in required if key not in keys)
    if missing:
        raise MemoryResumePackageValidationError(
            f"Resume package evidence ref missing keys: {', '.join(missing)}"
        )
    return ResumePackageEvidenceRef(
        context_id=keys["context_id"],
        content_hash=keys["content_hash"],
        source=keys["source"],
        created_at=_parse_datetime(keys["created_at"]),
        observed_updated_at=_parse_datetime(keys["observed_updated_at"]),
    )


def _parse_datetime(value: str) -> datetime:
    """Parse one canonical ISO-8601 timestamp.

    Args:
        value: ISO-8601 timestamp with timezone.

    Returns:
        Parsed aware datetime.

    Raises:
        MemoryResumePackageValidationError: When the timestamp is malformed.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MemoryResumePackageValidationError(
            f"Resume package timestamp is malformed: {value}"
        ) from exc
    if parsed.tzinfo is None:
        raise MemoryResumePackageValidationError(
            f"Resume package timestamp must be timezone-aware: {value}"
        )
    return parsed


def _parse_revision(value: str) -> int:
    """Parse one canonical revision integer.

    Args:
        value: Canonical decimal revision.

    Returns:
        Parsed revision.

    Raises:
        MemoryResumePackageValidationError: When the revision is malformed.
    """
    try:
        return int(value)
    except ValueError as exc:
        raise MemoryResumePackageValidationError(
            f"Resume package revision is malformed: {value}"
        ) from exc


def _scalar_section(heading: str, value: str) -> list[str]:
    """Render one single-line scalar section.

    Args:
        heading: Heading text for this section.
        value: Single-line scalar value.

    Returns:
        Rendered section lines.
    """
    return [f"## {heading}", value, ""]


def _bullet_section(heading: str, items: tuple[str, ...] | str) -> list[str]:
    """Render one bullet-list section.

    Args:
        heading: Heading text for this section.
        items: Bullet values, or one scalar rendered as a single bullet.

    Returns:
        Rendered section lines.
    """
    values = (items,) if isinstance(items, str) else items
    lines = [f"## {heading}"]
    lines.extend(f"{_BULLET_PREFIX}{value}" for value in values)
    lines.append("")
    return lines


def _item_section(
    heading: str,
    items: tuple[ResumePackageAttributedItem, ...],
) -> list[str]:
    """Render one attributed-item section.

    Args:
        heading: Heading text for this section.
        items: Attributed items.

    Returns:
        Rendered section lines.
    """
    if not items:
        return [f"## {heading}", "", ""]
    lines = [f"## {heading}"]
    for item in items:
        lines.append(f"{_ITEM_TEXT_PREFIX}{item.text}")
        lines.append(f"{_ITEM_SOURCE_PREFIX}{item.source_context_id}")
    lines.append("")
    return lines


def _key_section(
    heading: str,
    entries: tuple[tuple[str, str], ...],
) -> list[str]:
    """Render one canonical key-value section.

    Args:
        heading: Heading text for this section.
        entries: Ordered key/value entries.

    Returns:
        Rendered section lines.
    """
    lines = [f"## {heading}"]
    lines.extend(f"{_BULLET_PREFIX}{key}: {value}" for key, value in entries)
    lines.append("")
    return lines


def _evidence_summary_section(
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
) -> list[str]:
    """Render the compact-required evidence summary section.

    Args:
        evidence_refs: Observed evidence references.

    Returns:
        Rendered section lines linking every evidence id.
    """
    lines = [f"## {_EVIDENCE_SUMMARY}"]
    lines.extend(
        f"{_BULLET_PREFIX}{evidence_ref.context_id} observed content hash "
        f"{evidence_ref.content_hash} at seal time."
        for evidence_ref in evidence_refs
    )
    lines.append("")
    return lines


def _evidence_refs_section(
    evidence_refs: tuple[ResumePackageEvidenceRef, ...],
) -> list[str]:
    """Render the structured evidence-ref section.

    Args:
        evidence_refs: Observed evidence references.

    Returns:
        Rendered section lines with one canonical block per ref.
    """
    lines = [f"## {_EVIDENCE_REFS}"]
    for evidence_ref in evidence_refs:
        lines.append(f"- context_id: {evidence_ref.context_id}")
        lines.append(f"  content_hash: {evidence_ref.content_hash}")
        lines.append(f"  source: {evidence_ref.source}")
        lines.append(f"  created_at: {_isoformat(evidence_ref.created_at)}")
        lines.append(
            f"  observed_updated_at: {_isoformat(evidence_ref.observed_updated_at)}"
        )
    lines.append("")
    return lines


def _restore_prompt(
    *,
    lineage_id: str,
    package_revision: int,
    next_single_action: str,
) -> str:
    """Build the canonical restore prompt line.

    Args:
        lineage_id: Stable lineage identity for the handoff chain.
        package_revision: Sealed monotonic revision within the lineage.
        next_single_action: The single next action for the resuming worker.

    Returns:
        Single-line restore prompt.
    """
    return (
        f"Resume lineage {lineage_id} at revision {package_revision}; single "
        f"next action: {next_single_action}"
    )


def _isoformat(value: datetime) -> str:
    """Format one datetime in the canonical UTC ISO-8601 form.

    Args:
        value: Aware datetime value.

    Returns:
        Canonical ISO-8601 text.
    """
    return aware_utc_datetime(value).isoformat()
