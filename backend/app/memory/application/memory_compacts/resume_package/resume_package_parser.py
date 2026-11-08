"""Parse sealed resume-package Markdown without changing its stored format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.memory.application.memory_compacts.resume_package.resume_package_contracts import (
    ResumePackageAttributedItem,
    ResumePackageEvidenceRef,
)
from app.memory.application.memory_compacts.resume_package.resume_package_markdown_enums import (
    ResumePackageField,
    ResumePackageHeading,
    ResumePackageMarkdownPrefix,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryResumePackageValidationError,
)

_HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$")
_KEY_LINE_PATTERN = re.compile(r"^- ([a-z_]+): (.*)$")
_EVIDENCE_KEY_LINE_PATTERN = re.compile(r"^  ([a-z_]+): (.*)$")
_SCALAR_SECTIONS: tuple[str, ...] = (
    ResumePackageHeading.SUMMARY.value,
    ResumePackageHeading.GOAL.value,
    ResumePackageHeading.CURRENT_STATE.value,
    ResumePackageHeading.NEXT_SINGLE_ACTION.value,
    ResumePackageHeading.RESTORE_PROMPT.value,
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


class ResumeMarkdownSections:
    """Read canonical Markdown sections and their optional key values."""

    @staticmethod
    def split(markdown_body: str) -> dict[str, tuple[str, ...]]:
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

    @staticmethod
    def single_scalar_line(
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

    @staticmethod
    def key_value(
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

    @staticmethod
    def optional_key_value(
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
        value = ResumeMarkdownSections.key_value(sections, heading, key)
        return None if value == "none" else value

    @staticmethod
    def optional_lineage_key(
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
        lines = sections.get(ResumePackageHeading.LINEAGE.value)
        if lines is None:
            return None
        for line in lines:
            match = _KEY_LINE_PATTERN.match(line)
            if match is not None and match.group(1) == key:
                return None if match.group(2) == "none" else match.group(2)
        return None


class ResumePackageMarkdownParser:
    """Parse canonical package fields and attributed evidence records."""

    @staticmethod
    def parse(markdown_body: str) -> ParsedResumePackageBody:
        """Parse one canonical resume package body back into structured fields.

        Args:
            markdown_body: Stored Memory Compact Markdown body.

        Returns:
            Parsed structured package fields.

        Raises:
            MemoryResumePackageValidationError: When the body is not a canonical
                resume package body.
        """
        sections = ResumeMarkdownSections.split(markdown_body)
        scalar = {
            heading: ResumeMarkdownSections.single_scalar_line(sections, heading)
            for heading in _SCALAR_SECTIONS
        }
        return ParsedResumePackageBody(
            summary=scalar[ResumePackageHeading.SUMMARY.value],
            goal=scalar[ResumePackageHeading.GOAL.value],
            current_state=scalar[ResumePackageHeading.CURRENT_STATE.value],
            next_single_action=scalar[ResumePackageHeading.NEXT_SINGLE_ACTION.value],
            restore_prompt=scalar[ResumePackageHeading.RESTORE_PROMPT.value],
            accepted_changes=ResumePackageMarkdownParser._parse_items(
                sections, ResumePackageHeading.ACCEPTED_CHANGES.value
            ),
            constraints=ResumePackageMarkdownParser._parse_items(
                sections, ResumePackageHeading.CONSTRAINTS.value
            ),
            verified_complete=ResumePackageMarkdownParser._parse_bullets(
                sections, ResumePackageHeading.VERIFIED_COMPLETE.value
            ),
            implemented_unverified=ResumePackageMarkdownParser._parse_bullets(
                sections, ResumePackageHeading.IMPLEMENTED_UNVERIFIED.value
            ),
            unfinished_tasks=ResumePackageMarkdownParser._parse_bullets(
                sections, ResumePackageHeading.UNFINISHED_TASKS.value
            ),
            uncertain_results=ResumePackageMarkdownParser._parse_bullets(
                sections, ResumePackageHeading.UNCERTAIN_RESULTS.value
            ),
            blockers=ResumePackageMarkdownParser._parse_bullets(
                sections, ResumePackageHeading.BLOCKERS.value
            ),
            covered_from=_parse_datetime(
                ResumeMarkdownSections.key_value(
                    sections,
                    ResumePackageHeading.COVERAGE.value,
                    ResumePackageField.COVERED_FROM.value,
                )
            ),
            covered_to=_parse_datetime(
                ResumeMarkdownSections.key_value(
                    sections,
                    ResumePackageHeading.COVERAGE.value,
                    ResumePackageField.COVERED_TO.value,
                )
            ),
            evidence_refs=ResumePackageMarkdownParser._parse_evidence_refs(sections),
            lineage_id=ResumeMarkdownSections.key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.LINEAGE_ID.value,
            ),
            worker_id=ResumeMarkdownSections.optional_key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.WORKER_ID.value,
            ),
            run_id=ResumeMarkdownSections.optional_key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.RUN_ID.value,
            ),
            workspace_id=ResumeMarkdownSections.optional_key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.WORKSPACE_ID.value,
            ),
            session_id=ResumeMarkdownSections.optional_key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.SESSION_ID.value,
            ),
            previous_package_id=ResumeMarkdownSections.optional_key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.PREVIOUS_PACKAGE_ID.value,
            ),
            package_revision=_parse_revision(
                ResumeMarkdownSections.key_value(
                    sections,
                    ResumePackageHeading.LINEAGE.value,
                    ResumePackageField.PACKAGE_REVISION.value,
                )
            ),
            draft_hash=ResumeMarkdownSections.key_value(
                sections,
                ResumePackageHeading.LINEAGE.value,
                ResumePackageField.DRAFT_HASH.value,
            ),
            request_id=ResumeMarkdownSections.optional_lineage_key(
                sections, ResumePackageField.REQUEST_ID.value
            ),
        )

    @staticmethod
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
            if line.startswith(ResumePackageMarkdownPrefix.ITEM_TEXT.value):
                if pending_text is not None:
                    raise MemoryResumePackageValidationError(
                        f"Resume package item missing source attribution: {heading}"
                    )
                pending_text = line[len(ResumePackageMarkdownPrefix.ITEM_TEXT.value) :]
                continue
            if line.startswith(ResumePackageMarkdownPrefix.ITEM_SOURCE.value):
                if pending_text is None:
                    raise MemoryResumePackageValidationError(
                        f"Resume package item source without text: {heading}"
                    )
                items.append(
                    ResumePackageAttributedItem(
                        text=pending_text,
                        source_context_id=line[
                            len(ResumePackageMarkdownPrefix.ITEM_SOURCE.value) :
                        ],
                    )
                )
                pending_text = None
        if pending_text is not None:
            raise MemoryResumePackageValidationError(
                f"Resume package item missing source attribution: {heading}"
            )
        return tuple(items)

    @staticmethod
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
            line[len(ResumePackageMarkdownPrefix.BULLET.value) :]
            for line in sections.get(heading, ())
            if line.startswith(ResumePackageMarkdownPrefix.BULLET.value)
        )

    @staticmethod
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
        lines = sections.get(ResumePackageHeading.EVIDENCE_REFS.value)
        if lines is None:
            raise MemoryResumePackageValidationError(
                f"Resume package body missing section: {ResumePackageHeading.EVIDENCE_REFS.value}"
            )
        evidence_refs: list[ResumePackageEvidenceRef] = []
        current_keys: dict[str, str] = {}
        for line in lines:
            if line.startswith("- context_id:"):
                current_keys = {
                    ResumePackageField.CONTEXT_ID.value: line[
                        len("- context_id:") :
                    ].lstrip()
                }
                continue
            if not line.startswith("  "):
                continue
            match = _EVIDENCE_KEY_LINE_PATTERN.match(line)
            if match is None or not current_keys:
                continue
            current_keys[match.group(1)] = match.group(2)
            if match.group(1) == ResumePackageField.OBSERVED_UPDATED_AT.value:
                evidence_refs.append(
                    ResumePackageMarkdownParser._evidence_ref_from_keys(current_keys)
                )
                current_keys = {}
        if current_keys:
            raise MemoryResumePackageValidationError(
                "Resume package evidence ref is incomplete"
            )
        return tuple(evidence_refs)

    @staticmethod
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
            ResumePackageField.CONTEXT_ID.value,
            ResumePackageField.CONTENT_HASH.value,
            ResumePackageField.SOURCE.value,
            ResumePackageField.CREATED_AT.value,
            ResumePackageField.OBSERVED_UPDATED_AT.value,
        )
        missing = tuple(key for key in required if key not in keys)
        if missing:
            raise MemoryResumePackageValidationError(
                f"Resume package evidence ref missing keys: {', '.join(missing)}"
            )
        return ResumePackageEvidenceRef(
            context_id=keys[ResumePackageField.CONTEXT_ID.value],
            content_hash=keys[ResumePackageField.CONTENT_HASH.value],
            source=keys[ResumePackageField.SOURCE.value],
            created_at=_parse_datetime(keys[ResumePackageField.CREATED_AT.value]),
            observed_updated_at=_parse_datetime(
                keys[ResumePackageField.OBSERVED_UPDATED_AT.value]
            ),
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
