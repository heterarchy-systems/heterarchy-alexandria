"""Pure helpers for Obsidian note rendering and identifiers."""

from __future__ import annotations

from datetime import UTC, datetime

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianSaveNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.frontmatter import timestamp_text
from app.obsidian.infrastructure.markdown.paths import safe_filename
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_known_frontmatter_metadata,
)
from app.shared.types.extra_types import JSONObject


def frontmatter_for_save(
    payload: ObsidianSaveNote,
    note_id: str,
    title: str,
    redaction_warnings: list[str],
) -> JSONObject:
    """Build frontmatter for a note save."""
    now = timestamp_text(datetime.now(UTC))
    frontmatter = dict(payload.frontmatter)
    frontmatter.update(
        {
            "alexandria_type": payload.alexandria_type.value,
            "id": note_id,
            "title": title,
            "tags": payload.tags,
            "status": payload.status,
            "created_at": frontmatter.get("created_at") or now,
            "updated_at": frontmatter.get("updated_at") or now,
            "source": payload.source,
        }
    )
    if payload.project is not None:
        frontmatter["project"] = payload.project
    if redaction_warnings:
        frontmatter["redaction_warnings"] = redaction_warnings
    normalize_known_frontmatter_metadata(frontmatter)
    return frontmatter


def default_note_path(
    root: str,
    note_type: AlexandriaNoteType,
    title: str,
) -> str:
    """Build the default note path."""
    folder = {
        AlexandriaNoteType.CONTEXT: "Contexts/Projects",
        AlexandriaNoteType.MEMORY_COMPACT: "Memory Compacts",
        AlexandriaNoteType.SKILL: "Skills/Drafts",
        AlexandriaNoteType.PROMPT: "Prompts/Task Prompts",
        AlexandriaNoteType.JOB_PLAN: "Jobs",
        AlexandriaNoteType.IMPLEMENTATION_HISTORY: "Implementation History",
    }[note_type]
    return f"{root}/{folder}/{safe_filename(title)}"


def default_folders(root: str) -> tuple[str, ...]:
    """Build the default Obsidian folder set."""
    return (
        root,
        f"{root}/Memory Compacts",
        f"{root}/_Inbox/Captures",
        f"{root}/_Inbox/To Promote",
        f"{root}/_Inbox/Unsorted",
        f"{root}/Contexts/Decisions",
        f"{root}/Contexts/Handoffs",
        f"{root}/Contexts/Bug Root Causes",
        f"{root}/Contexts/Projects",
        f"{root}/Contexts/Research",
        f"{root}/Contexts/Plans",
        f"{root}/Skills/Active",
        f"{root}/Skills/Drafts",
        f"{root}/Skills/Deprecated",
        f"{root}/Prompts/System",
        f"{root}/Prompts/Agent Roles",
        f"{root}/Prompts/Task Prompts",
        f"{root}/Prompts/Eval Prompts",
        f"{root}/Implementation History",
        f"{root}/Indexes",
        f"{root}/Archive",
        f"{root}/Jobs",
    )


def start_here_body() -> str:
    """Build the Start Here note body."""
    return """# Alexandria START HERE

## Summary
This Obsidian vault stores heterarchy-alexandria long-term memory, skills, prompts, and Memory Compacts as canonical Markdown.

## Storage Rule
Obsidian Markdown is the source of truth. PostgreSQL search state is a rebuildable projection.

## Restore Prompt
Start with the current Memory Compact, then search Contexts, Skills, and Prompts by task.
"""


def conversation_id() -> str:
    """Create a generic conversation identifier."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"conversation_{timestamp}_{new_uuid()[:8]}"
