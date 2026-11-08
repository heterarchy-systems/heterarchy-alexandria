"""Canonical Markdown rendering for durable resume packages."""

from __future__ import annotations

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
from app.shared.types.types_convert_utils import aware_utc_datetime


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
    lines.extend(
        ResumeMarkdownSectionRenderer._scalar_section(
            ResumePackageHeading.SUMMARY.value, summary
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._scalar_section(
            ResumePackageHeading.GOAL.value, goal
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._item_section(
            ResumePackageHeading.ACCEPTED_CHANGES.value, accepted_changes
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._item_section(
            ResumePackageHeading.CONSTRAINTS.value, constraints
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.VERIFIED_COMPLETE.value, verified_complete
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.IMPLEMENTED_UNVERIFIED.value, implemented_unverified
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.UNFINISHED_TASKS.value, unfinished_tasks
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.UNCERTAIN_RESULTS.value, uncertain_results
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.BLOCKERS.value, blockers
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._scalar_section(
            ResumePackageHeading.CURRENT_STATE.value, current_state
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.DURABLE_DECISIONS.value,
            (
                "Accepted changes and constraints above stay durable for this "
                "lineage; each item keeps its evidence attribution."
            ),
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.RISKS_AND_BLOCKERS.value,
            f"{len(blockers)} recorded blockers; see the Blockers section for "
            "the current list.",
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._bullet_section(
            ResumePackageHeading.NEXT_ACTIONS.value, next_single_action
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._scalar_section(
            ResumePackageHeading.NEXT_SINGLE_ACTION.value, next_single_action
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._scalar_section(
            ResumePackageHeading.RESTORE_PROMPT.value,
            _restore_prompt(
                lineage_id=lineage_id,
                package_revision=package_revision,
                next_single_action=next_single_action,
            ),
        )
    )
    lines.extend(
        ResumeMarkdownSectionRenderer._key_section(
            ResumePackageHeading.COVERAGE.value,
            (
                (ResumePackageField.COVERED_FROM.value, _isoformat(covered_from)),
                (ResumePackageField.COVERED_TO.value, _isoformat(covered_to)),
                (
                    ResumePackageField.PROJECT.value,
                    project if project is not None else "default",
                ),
            ),
        )
    )
    lines.extend(ResumeMarkdownSectionRenderer._evidence_summary_section(evidence_refs))
    lines.extend(ResumeMarkdownSectionRenderer._evidence_refs_section(evidence_refs))
    lines.extend(
        ResumeMarkdownSectionRenderer._key_section(
            ResumePackageHeading.LINEAGE.value,
            (
                (ResumePackageField.LINEAGE_ID.value, lineage_id),
                (
                    ResumePackageField.WORKER_ID.value,
                    worker_id if worker_id is not None else "none",
                ),
                (
                    ResumePackageField.RUN_ID.value,
                    run_id if run_id is not None else "none",
                ),
                (
                    ResumePackageField.WORKSPACE_ID.value,
                    workspace_id if workspace_id is not None else "none",
                ),
                (
                    ResumePackageField.SESSION_ID.value,
                    session_id if session_id is not None else "none",
                ),
                (
                    ResumePackageField.PREVIOUS_PACKAGE_ID.value,
                    previous_package_id if previous_package_id is not None else "none",
                ),
                (ResumePackageField.PACKAGE_REVISION.value, str(package_revision)),
                (ResumePackageField.DRAFT_HASH.value, draft_hash),
                (
                    ResumePackageField.REQUEST_ID.value,
                    request_id if request_id is not None else "none",
                ),
            ),
        )
    )
    return "\n".join(lines) + "\n"


class ResumeMarkdownSectionRenderer:
    """Render canonical Markdown sections with their field owners."""

    @staticmethod
    def _scalar_section(heading: str, value: str) -> list[str]:
        """Render one single-line scalar section.

        Args:
            heading: Heading text for this section.
            value: Single-line scalar value.

        Returns:
            Rendered section lines.
        """
        return [f"## {heading}", value, ""]

    @staticmethod
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
        lines.extend(
            f"{ResumePackageMarkdownPrefix.BULLET.value}{value}" for value in values
        )
        lines.append("")
        return lines

    @staticmethod
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
            lines.append(f"{ResumePackageMarkdownPrefix.ITEM_TEXT.value}{item.text}")
            lines.append(
                f"{ResumePackageMarkdownPrefix.ITEM_SOURCE.value}{item.source_context_id}"
            )
        lines.append("")
        return lines

    @staticmethod
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
        lines.extend(
            f"{ResumePackageMarkdownPrefix.BULLET.value}{key}: {value}"
            for key, value in entries
        )
        lines.append("")
        return lines

    @staticmethod
    def _evidence_summary_section(
        evidence_refs: tuple[ResumePackageEvidenceRef, ...],
    ) -> list[str]:
        """Render the compact-required evidence summary section.

        Args:
            evidence_refs: Observed evidence references.

        Returns:
            Rendered section lines linking every evidence id.
        """
        lines = [f"## {ResumePackageHeading.EVIDENCE_SUMMARY.value}"]
        lines.extend(
            f"{ResumePackageMarkdownPrefix.BULLET.value}{evidence_ref.context_id} observed content hash "
            f"{evidence_ref.content_hash} at seal time."
            for evidence_ref in evidence_refs
        )
        lines.append("")
        return lines

    @staticmethod
    def _evidence_refs_section(
        evidence_refs: tuple[ResumePackageEvidenceRef, ...],
    ) -> list[str]:
        """Render the structured evidence-ref section.

        Args:
            evidence_refs: Observed evidence references.

        Returns:
            Rendered section lines with one canonical block per ref.
        """
        lines = [f"## {ResumePackageHeading.EVIDENCE_REFS.value}"]
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
