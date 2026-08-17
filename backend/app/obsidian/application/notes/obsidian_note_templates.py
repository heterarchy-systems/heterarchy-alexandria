"""Pure helpers for Obsidian note rendering and librarian responses."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from app.obsidian.application.notes.frontmatter_metadata_normalization import (
    normalize_known_frontmatter_metadata,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianChunkIndex,
    ObsidianLibrarianAsk,
    ObsidianSaveNote,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote, ObsidianSearchHit
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.markdown.frontmatter import (
    FrontmatterValue,
    frontmatter_text,
    timestamp_text,
)
from app.obsidian.infrastructure.markdown.paths import safe_filename
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.search.markdown_text_chunking import split_markdown_text
from app.shared.types.extra_types import JSONObject
from app.shared.utils.text_metrics import count_word_tokens

LIBRARIAN_OPERATIONS_FOLDER = "_Ops/Librarian"


def frontmatter_for_save(
    payload: ObsidianSaveNote,
    *,
    note_id: str,
    title: str,
    redaction_warnings: list[str],
) -> JSONObject:
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


def chunks_for_body(body: str, *, title: str) -> list[ObsidianChunkIndex]:
    if not body.strip():
        return [
            ObsidianChunkIndex(
                chunk_index=0,
                heading_path=None,
                text="",
                content_hash=sha256_text(""),
                token_count=0,
            )
        ]
    return [
        ObsidianChunkIndex(
            chunk_index=chunk.chunk_index,
            heading_path=chunk.heading,
            text=chunk.content,
            content_hash=sha256_text(chunk.content),
            token_count=count_word_tokens(chunk.content),
        )
        for chunk in split_markdown_text(title=title, content=body)
    ]


def title_from_document(
    frontmatter: Mapping[str, FrontmatterValue],
    body: str,
    path: Path,
) -> str:
    title = frontmatter_text(frontmatter, "title")
    if title:
        return title
    for line in body.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return path.stem


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_note_path(
    *,
    root: str,
    note_type: AlexandriaNoteType,
    title: str,
) -> str:
    folder = {
        AlexandriaNoteType.CONTEXT: "Contexts/Projects",
        AlexandriaNoteType.MEMORY_COMPACT: "Memory Compacts",
        AlexandriaNoteType.SKILL: "Skills/Drafts",
        AlexandriaNoteType.PROMPT: "Prompts/Task Prompts",
        AlexandriaNoteType.LIBRARIAN_BRIEF: f"{LIBRARIAN_OPERATIONS_FOLDER}/Briefs",
        AlexandriaNoteType.LIBRARIAN_CHAT: f"{LIBRARIAN_OPERATIONS_FOLDER}/Chats",
        AlexandriaNoteType.JOB_PLAN: "Jobs",
        AlexandriaNoteType.IMPLEMENTATION_HISTORY: "Implementation History",
    }[note_type]
    return f"{root}/{folder}/{safe_filename(title)}"


def default_folders(root: str) -> tuple[str, ...]:
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
        f"{root}/{LIBRARIAN_OPERATIONS_FOLDER}/Briefs",
        f"{root}/{LIBRARIAN_OPERATIONS_FOLDER}/Chats",
        f"{root}/{LIBRARIAN_OPERATIONS_FOLDER}/Reports",
        f"{root}/{LIBRARIAN_OPERATIONS_FOLDER}/Research Results",
        f"{root}/{LIBRARIAN_OPERATIONS_FOLDER}/Skill Acquisition",
        f"{root}/Implementation History",
        f"{root}/Indexes",
        f"{root}/Archive",
        f"{root}/Jobs",
    )


def start_here_body() -> str:
    return """# Alexandria START HERE

## Summary
This Obsidian vault stores heterarchy-alexandria long-term memory, skills, prompts, Memory Compacts, and librarian transcripts as canonical Markdown.

## Storage Rule
Obsidian Markdown is the source of truth. PostgreSQL search state is a rebuildable projection.

## Restore Prompt
Start with the current Memory Compact, then search Contexts, Skills, and Prompts by task.
"""


def librarian_answer(
    payload: ObsidianLibrarianAsk,
    hits: list[ObsidianSearchHit],
    active_note: ObsidianNote | None,
) -> str:
    lines = [
        "# Alexandria Librarian Context Packet",
        "",
        "아래 컨텍스트를 사용해 LLM librarian이 사용자 질문에 답해야 합니다.",
        "",
        "## User Question",
        payload.query,
    ]
    if active_note is not None:
        lines.extend(
            [
                "",
                "## Active Note",
                f"- path: `{active_note.relative_path}`",
                f"- title: {active_note.title}",
                "",
                _bounded_context(active_note.body),
            ]
        )
    if payload.selection:
        lines.extend(["", "## User Selection", _bounded_context(payload.selection)])
    lines.append("")
    lines.append("## Retrieved Sources")
    if hits:
        lines.extend(
            f"- [[{hit.note.relative_path.removesuffix('.md')}]] — {hit.excerpt}"
            for hit in hits
        )
    else:
        lines.append("- none")
    return "\n".join(lines)


def _bounded_context(text: str, limit: int = 4_000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit]}\n…[context truncated]"


def source_ref(note: ObsidianNote) -> JSONObject:
    return {
        "id": note.note_id,
        "alexandria_type": note.alexandria_type.value,
        "path": note.relative_path,
        "title": note.title,
        "wikilink": f"[[{note.relative_path.removesuffix('.md')}]]",
    }


def source_refs_for_librarian(
    hits: list[ObsidianSearchHit],
    active_note: ObsidianNote | None,
) -> list[JSONObject]:
    refs: list[JSONObject] = []
    seen_note_ids: set[str] = set()
    if active_note is not None:
        refs.append(source_ref(active_note))
        seen_note_ids.add(active_note.note_id)
    for hit in hits:
        if hit.note.note_id in seen_note_ids:
            continue
        refs.append(source_ref(hit.note))
        seen_note_ids.add(hit.note.note_id)
    return refs


def conversation_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"librarian_chat_{timestamp}_{new_uuid()[:8]}"


def librarian_transcript_body(
    payload: ObsidianLibrarianAsk,
    answer: str,
    hits: list[ObsidianSearchHit],
) -> str:
    source_lines = "\n".join(
        f"- [[{hit.note.relative_path.removesuffix('.md')}]] (`id: {hit.note.note_id}`)"
        for hit in hits
    )
    return f"""# Librarian Chat

## User
{payload.query}

## Selection
{payload.selection or ""}

## Librarian
{answer}

## Sources
{source_lines}
"""
