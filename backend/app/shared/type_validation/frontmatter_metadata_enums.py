"""Enum contracts for type-sensitive frontmatter metadata normalization."""

from __future__ import annotations

from enum import StrEnum


class StringCollectionField(StrEnum):
    """Known frontmatter fields whose values normalize to string lists."""

    TAGS = "tags"
    ARTIFACT_REFS = "artifact_refs"
    EVIDENCE_REFS = "evidence_refs"
    CONFLICT_SET_IDS = "conflict_set_ids"
    EVIDENCE_URLS = "evidence_urls"
    LINKED_NOTE_IDS = "linked_note_ids"
    REDACTION_WARNINGS = "redaction_warnings"
    REQUIRED_TOOLS = "required_tools"
    SUPERSEDES = "supersedes"
    WHEN_NOT_TO_USE = "when_not_to_use"
    WHEN_TO_USE = "when_to_use"


class BooleanField(StrEnum):
    """Known frontmatter fields whose values normalize to booleans."""

    ACTIVATE_REQUESTED = "activate_requested"
    IS_CURRENT = "is_current"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    SAFE_TO_PUBLISH = "safe_to_publish"
    SOURCE_OF_TRUTH = "source_of_truth"
