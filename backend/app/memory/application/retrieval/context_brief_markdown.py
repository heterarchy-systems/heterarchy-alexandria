"""Byte-exact markdown accumulator and section ordering for Context Briefs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

_SECTION_HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$")

_CORE_SECTION_RANKS: tuple[tuple[str, ...], ...] = (
    ("goal",),
    ("constraint",),
    ("unconfirmed", "unverified", "uncertain"),
    ("next action", "next single action", "next step"),
)


@dataclass(frozen=True, slots=True)
class BriefSection:
    """One HANDOFF-style markdown section parsed from chunk content."""

    heading: str
    text: str


class BudgetedMarkdown:
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
        cost = len(text.encode("utf-8")) + self.append_overhead()
        return cost <= self.remaining()

    def fits_all(self, lines: Sequence[str]) -> bool:
        """Return whether a block of appended lines would stay within budget.

        Args:
            lines: Candidate lines appended together.

        Returns:
            Whether appending all lines keeps the render within budget.
        """
        if not lines:
            return True
        cost = sum(len(line.encode("utf-8")) + 1 for line in lines)
        if not self._lines:
            cost -= 1
        return cost <= self.remaining()

    def append(self, text: str) -> None:
        """Append one line to the render.

        Args:
            text: Line to append; callers must check ``fits`` first.
        """
        self._joined_bytes += len(text.encode("utf-8")) + self.append_overhead()
        self._lines.append(text)

    def render(self) -> str:
        """Return the rendered markdown.

        Returns:
            Rendered brief text within the byte budget.
        """
        return "\n".join(self._lines)


def parse_sections(content: str) -> list[BriefSection]:
    """Parse chunk content into HANDOFF-style markdown sections.

    Args:
        content: Chunk content to parse.

    Returns:
        Sections in source order; unheaded content becomes one section.
    """
    sections: list[BriefSection] = []
    heading = ""
    body_lines: list[str] = []
    for line in content.splitlines():
        matched = _SECTION_HEADING_PATTERN.match(line)
        if matched is None:
            body_lines.append(line)
            continue
        text = "\n".join(body_lines).strip()
        if heading or text:
            sections.append(BriefSection(heading=heading, text=text))
        heading = matched.group(1)
        body_lines = []
    text = "\n".join(body_lines).strip()
    if heading or text:
        sections.append(BriefSection(heading=heading, text=text))
    return sections


def delivery_order(sections: list[BriefSection]) -> list[BriefSection]:
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


def append_frame(render: BudgetedMarkdown, text: str) -> None:
    """Append one structural line, truncating it when the budget is tight.

    Args:
        render: Budgeted renderer shared by the whole brief.
        text: Structural line to append.
    """
    if render.fits(text):
        render.append(text)
        return
    rendered = truncate_to_bytes(text, render.remaining())
    if rendered:
        render.append(rendered)


def truncate_to_bytes(text: str, max_bytes: int) -> str:
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
