"""Context Harness linting and secret-aware redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    ContextStorageStatus,
)
from app.memory.domain.types.context_payload_types import (
    ContextLintNormalizedPayload,
    SaveSuggestionPayload,
)
from app.shared.utils.secret_redaction import redact_secret_text

HEADING_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)

REQUIRED_HEADINGS_BY_KIND: dict[ContextKind, tuple[str, ...]] = {
    ContextKind.HANDOFF: ("Summary", "Current State", "Next Actions", "Restore Prompt"),
    ContextKind.COMPACT: ("Summary", "Current State", "Next Actions", "Restore Prompt"),
    ContextKind.DECISION: ("Summary", "Key Decisions", "Evidence"),
    ContextKind.BUG_ROOT_CAUSE: ("Summary", "Current State", "Evidence"),
    ContextKind.PLAN: ("Summary", "Current State", "Next Actions"),
    ContextKind.RESEARCH: ("Summary", "Evidence"),
    ContextKind.USAGE: ("Summary", "Evidence"),
    ContextKind.MEMORY: ("Summary", "Restore Prompt"),
}


@dataclass(frozen=True, slots=True)
class ContextLintInput:
    """Input contract for linting context content."""

    kind: ContextKind
    title: str
    content: str
    summary: str | None
    project: str | None
    scope: ContextScope = ContextScope.PROJECT
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    visibility: ContextScope = ContextScope.PROJECT
    source_agent: str = "Hermes"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize caller-provided tags to an immutable sequence."""
        object.__setattr__(self, "tags", tuple(self.tags))


@dataclass(frozen=True, slots=True)
class ContextLintResult:
    """Machine-readable lint result."""

    ok: bool
    status: ContextStorageStatus
    score: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    suggestions: tuple[str, ...]
    redacted_content: str
    redaction_report: tuple[str, ...]
    save_suggestion: SaveSuggestionPayload
    normalized: ContextLintNormalizedPayload

    def __post_init__(self) -> None:
        """Normalize lint findings to immutable sequences."""
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "suggestions", tuple(self.suggestions))
        object.__setattr__(self, "redaction_report", tuple(self.redaction_report))


def lint_context(payload: ContextLintInput) -> ContextLintResult:
    """Validate and redact a context before persistence.

    Args:
        payload: Context lint input.

    Returns:
        Lint result with redacted content and quality metadata.
    """
    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    title = payload.title.strip()
    content = payload.content.strip()
    summary = (payload.summary or "").strip()
    if not title:
        errors.append("title is required")
    if not content:
        errors.append("content is required")
    if not summary:
        warnings.append("summary is recommended")
        suggestions.append("Add a 1-3 sentence summary for better recall.")

    headings = {match.group(1).strip() for match in HEADING_PATTERN.finditer(content)}
    warnings.extend(
        f"missing heading: {required}"
        for required in REQUIRED_HEADINGS_BY_KIND[payload.kind]
        if required not in headings
    )

    redaction = redact_secret_text(content)

    if redaction.blocked:
        errors.extend(redaction.warnings)
        status = ContextStorageStatus.BLOCKED_SECRET_RISK
    elif redaction.redaction_count > 0:
        warnings.extend(redaction.warnings)
        status = ContextStorageStatus.REDACTED_AND_SAVED
    elif warnings:
        status = ContextStorageStatus.SAVED_WITH_WARNINGS
    else:
        status = ContextStorageStatus.SAVED

    score = max(0, 100 - len(errors) * 40 - len(warnings) * 8)
    if score < 70 and status is not ContextStorageStatus.BLOCKED_SECRET_RISK:
        status = ContextStorageStatus.PENDING_REVIEW
        warnings.append("quality score below review threshold")

    normalized: ContextLintNormalizedPayload = {
        "kind": payload.kind,
        "title": title,
        "summary": summary,
        "project": payload.project,
        "scope": payload.scope,
        "workspace_id": payload.workspace_id,
        "agent_id": payload.agent_id,
        "user_id": payload.user_id,
        "session_id": payload.session_id,
        "visibility": payload.visibility,
        "source_agent": payload.source_agent.strip(),
        "tags": sorted({tag.strip() for tag in payload.tags if tag.strip()}),
    }
    save_suggestion = _save_suggestion(payload.kind, payload.scope, content, summary)
    result = ContextLintResult(
        ok=not errors,
        status=status,
        score=score,
        errors=tuple(errors),
        warnings=tuple(warnings),
        suggestions=tuple(suggestions),
        redacted_content=redaction.redacted_content,
        redaction_report=tuple(redaction.warnings),
        save_suggestion=save_suggestion,
        normalized=normalized,
    )
    return result


def _save_suggestion(
    kind: ContextKind,
    scope: ContextScope,
    content: str,
    summary: str,
) -> SaveSuggestionPayload:
    should_save = kind in {
        ContextKind.DECISION,
        ContextKind.BUG_ROOT_CAUSE,
        ContextKind.HANDOFF,
        ContextKind.PLAN,
        ContextKind.COMPACT,
        ContextKind.RESEARCH,
        ContextKind.MEMORY,
    }
    lowered = f"{summary}\n{content}".lower()
    reason = "durable context kind is reusable"
    if "root cause" in lowered or "bug" in lowered:
        reason = "bug/root-cause signal detected"
        should_save = True
    elif "decision" in lowered or "decided" in lowered:
        reason = "project decision signal detected"
        should_save = True
    elif "workflow" in lowered or "handoff" in lowered:
        reason = "reusable workflow or handoff signal detected"
        should_save = True
    payload = SaveSuggestionPayload(
        should_save=should_save,
        suggested_kind=kind,
        suggested_scope=scope,
        reason=reason if should_save else "content looks transient",
    )
    return payload
