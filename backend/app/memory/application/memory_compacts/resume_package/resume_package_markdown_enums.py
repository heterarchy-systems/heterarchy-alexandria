"""Canonical resume-package Markdown field names and section markers."""

from __future__ import annotations

from enum import StrEnum


class ResumePackageHeading(StrEnum):
    """Canonical section headings in a sealed resume-package body."""

    SUMMARY = "Summary"
    GOAL = "Goal"
    ACCEPTED_CHANGES = "Accepted Changes"
    CONSTRAINTS = "Constraints"
    VERIFIED_COMPLETE = "Verified Complete"
    IMPLEMENTED_UNVERIFIED = "Implemented Unverified"
    UNFINISHED_TASKS = "Unfinished Tasks"
    UNCERTAIN_RESULTS = "Uncertain Results"
    BLOCKERS = "Blockers"
    CURRENT_STATE = "Current State"
    DURABLE_DECISIONS = "Durable Decisions"
    RISKS_AND_BLOCKERS = "Risks and Blockers"
    NEXT_ACTIONS = "Next Actions"
    NEXT_SINGLE_ACTION = "Next Single Action"
    RESTORE_PROMPT = "Restore Prompt"
    COVERAGE = "Coverage"
    EVIDENCE_SUMMARY = "Evidence Summary"
    EVIDENCE_REFS = "Evidence Refs"
    LINEAGE = "Lineage"


class ResumePackageField(StrEnum):
    """Canonical metadata keys used by coverage, lineage, and evidence sections."""

    COVERED_FROM = "covered_from"
    COVERED_TO = "covered_to"
    PROJECT = "project"
    LINEAGE_ID = "lineage_id"
    WORKER_ID = "worker_id"
    RUN_ID = "run_id"
    WORKSPACE_ID = "workspace_id"
    SESSION_ID = "session_id"
    PREVIOUS_PACKAGE_ID = "previous_package_id"
    PACKAGE_REVISION = "package_revision"
    DRAFT_HASH = "draft_hash"
    REQUEST_ID = "request_id"
    CONTEXT_ID = "context_id"
    CONTENT_HASH = "content_hash"
    SOURCE = "source"
    CREATED_AT = "created_at"
    OBSERVED_UPDATED_AT = "observed_updated_at"


class ResumePackageMarkdownPrefix(StrEnum):
    """Canonical list-item prefixes in structured Markdown sections."""

    ITEM_TEXT = "- text: "
    ITEM_SOURCE = "  source_context_id: "
    BULLET = "- "
