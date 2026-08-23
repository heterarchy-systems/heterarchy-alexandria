"""Alexandria note type alias normalization."""

from __future__ import annotations

from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.types.extra_types import JSONValue


def alexandria_note_type_input(value: JSONValue) -> JSONValue:
    """Normalize user/legacy note type aliases into public enum values.

    Args:
        value: Raw type value from request payloads or Markdown frontmatter.

    Returns:
        Normalized enum value string when recognized, otherwise the original value.
    """
    note_type = normalized_alexandria_note_type(value)
    if note_type is None:
        return value
    return note_type.value


def normalized_alexandria_note_type(
    value: JSONValue | AlexandriaNoteType,
) -> AlexandriaNoteType | None:
    """Return an Alexandria note type for canonical values and known aliases.

    Args:
        value: Raw type value from request payloads or Markdown frontmatter.

    Returns:
        Alexandria note type when the value is recognized; otherwise ``None``.
    """
    if isinstance(value, AlexandriaNoteType):
        return value
    if not isinstance(value, str):
        return None
    normalized = _normalized_type_token(value)
    if not normalized:
        return None
    try:
        return AlexandriaNoteType(normalized)
    except ValueError:
        return _NOTE_TYPE_ALIASES.get(normalized)


def _normalized_type_token(value: str) -> str:
    """Execute normalized type token.

    Args:
        value: Value being processed.

    Returns:
        str result produced by normalized type token.
    """
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


_NOTE_TYPE_ALIASES = {
    "brief": AlexandriaNoteType.LIBRARIAN_BRIEF,
    "chat": AlexandriaNoteType.LIBRARIAN_CHAT,
    "context_note": AlexandriaNoteType.CONTEXT,
    "decision": AlexandriaNoteType.CONTEXT,
    "decisions": AlexandriaNoteType.CONTEXT,
    "index": AlexandriaNoteType.CONTEXT,
    "indexes": AlexandriaNoteType.CONTEXT,
    "indices": AlexandriaNoteType.CONTEXT,
    "history": AlexandriaNoteType.IMPLEMENTATION_HISTORY,
    "histories": AlexandriaNoteType.IMPLEMENTATION_HISTORY,
    "implementation_histories": AlexandriaNoteType.IMPLEMENTATION_HISTORY,
    "job": AlexandriaNoteType.JOB_PLAN,
    "librarian_briefs": AlexandriaNoteType.LIBRARIAN_BRIEF,
    "librarian_chats": AlexandriaNoteType.LIBRARIAN_CHAT,
    "memory": AlexandriaNoteType.MEMORY_COMPACT,
    "memory_compacts": AlexandriaNoteType.MEMORY_COMPACT,
    "plan": AlexandriaNoteType.JOB_PLAN,
    "plans": AlexandriaNoteType.JOB_PLAN,
    "project_context": AlexandriaNoteType.CONTEXT,
    "prompt_template": AlexandriaNoteType.PROMPT,
    "prompt_templates": AlexandriaNoteType.PROMPT,
    "prompts": AlexandriaNoteType.PROMPT,
    "skills": AlexandriaNoteType.SKILL,
}
