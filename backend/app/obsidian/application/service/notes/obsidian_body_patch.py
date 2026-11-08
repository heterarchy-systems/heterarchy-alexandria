"""Byte-preserving plans for bounded body-only Markdown patches."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.obsidian.application.notes.frontmatter.obsidian_context_frontmatter_mapper import (
    context_content_hash,
    context_identity_from_frontmatter,
)
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.domain.obsidian_note_type_aliases import (
    normalized_alexandria_note_type,
)
from app.obsidian.infrastructure.markdown.frontmatter import (
    frontmatter_json,
    parse_markdown_document,
    split_frontmatter_region,
)
from app.shared.utils.secret_redaction import (
    AUTHORIZATION_HEADER_PATTERN,
    BEARER_TOKEN_PATTERN,
    HIGH_RISK_SECRET_PATTERNS,
    LONG_TOKEN_PATTERN,
    TOKEN_ASSIGNMENT_PATTERN,
    URL_PATTERN,
    redact_secret_text,
)

MAX_BODY_PATCH_REPLACEMENTS = 8
MAX_BODY_PATCH_TEXT_CHARS = 4096
MAX_BODY_PATCH_INPUT_BYTES = 262_144
_REDACTION_PLACEHOLDERS = (
    "<REDACTED_LONG_VALUE>",
    "<REDACTED>",
    "[BLOCKED_SECRET_CONTENT]",
)
_TOP_LEVEL_KEY_PATTERN = re.compile(r"^(?P<key>[A-Za-z0-9_-]+)\s*:")


@dataclass(frozen=True, slots=True)
class PreparedObsidianBodyPatch:
    """Validated source bytes after one bounded set of exact body patches."""

    source_bytes: bytes
    body_replacement_count: int
    managed_content_hash_updated: bool


def validate_body_patch_replacements(
    replacements: Sequence[tuple[str, str]],
) -> tuple[tuple[bytes, bytes], ...]:
    """Validate and encode a bounded set of caller-authored body spans."""
    if not replacements or len(replacements) > MAX_BODY_PATCH_REPLACEMENTS:
        raise ValueError("replacement_count")

    encoded: list[tuple[bytes, bytes]] = []
    old_values: set[str] = set()
    total_bytes = 0
    for old_text, new_text in replacements:
        if not old_text or old_text == new_text:
            raise ValueError("replacement_shape")
        if (
            len(old_text) > MAX_BODY_PATCH_TEXT_CHARS
            or len(new_text) > MAX_BODY_PATCH_TEXT_CHARS
        ):
            raise ValueError("replacement_size")
        if old_text in old_values:
            raise ValueError("duplicate_old_text")
        old_values.add(old_text)
        _validate_patch_text(old_text)
        _validate_patch_text(new_text)
        try:
            old_bytes = old_text.encode("utf-8")
            new_bytes = new_text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("replacement_encoding") from exc
        total_bytes += len(old_bytes) + len(new_bytes)
        encoded.append((old_bytes, new_bytes))

    if total_bytes > MAX_BODY_PATCH_INPUT_BYTES:
        raise ValueError("replacement_size")
    return tuple(encoded)


def prepare_body_patch_source(
    source_bytes: bytes,
    replacements: Sequence[tuple[bytes, bytes]],
) -> PreparedObsidianBodyPatch:
    """Apply unique exact byte spans to the body and update Context hash only.

    Frontmatter and body are split before matching. Replacement offsets are
    resolved against the original body and applied in one pass, so edits cannot
    cascade into later matches.
    """
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source_encoding") from exc
    if source_text.encode("utf-8") != source_bytes:
        raise ValueError("source_encoding")

    frontmatter, body = split_frontmatter_region(source_text)
    if frontmatter is None:
        raise ValueError("frontmatter_required")
    document = parse_markdown_document(source_text)
    body_bytes = body.encode("utf-8")
    protected_spans = _protected_source_byte_spans(body)
    spans: list[tuple[int, int, bytes]] = []
    for old_bytes, new_bytes in replacements:
        matches = _find_all_overlapping(body_bytes, old_bytes)
        if len(matches) != 1:
            raise ValueError("old_text_must_match_once_in_body")
        start = matches[0]
        end = start + len(old_bytes)
        if any(
            start < protected_end and protected_start < end
            for protected_start, protected_end in protected_spans
        ):
            raise ValueError("replacement_overlaps_protected_source")
        spans.append((start, end, new_bytes))

    ordered_spans = sorted(spans, key=lambda span: span[0])
    previous_end = -1
    for start, end, _replacement in ordered_spans:
        if start < previous_end:
            raise ValueError("replacement_spans_overlap")
        previous_end = end

    patched_body = _apply_body_spans(body_bytes, ordered_spans)
    expected_protected_spans = _map_protected_spans(protected_spans, ordered_spans)
    if _merge_spans(_protected_source_byte_spans(patched_body.decode("utf-8"))) != (
        _merge_spans(expected_protected_spans)
    ):
        raise ValueError("replacement_creates_protected_source")
    frontmatter_bytes = frontmatter.encode("utf-8")
    managed_hash_updated = False
    frontmatter_values = frontmatter_json(document.frontmatter)
    note_type_value = frontmatter_values.get("alexandria_type")
    if note_type_value is None:
        note_type_value = frontmatter_values.get("type")
    if note_type_value is None:
        note_type_value = frontmatter_values.get("item_type")
    note_type = normalized_alexandria_note_type(note_type_value)

    if note_type is AlexandriaNoteType.CONTEXT and "content_hash" in frontmatter_values:
        current_content_hash = frontmatter_values["content_hash"]
        if not isinstance(current_content_hash, str):
            raise ValueError("managed_content_hash_not_scalar")
        try:
            candidate_document = parse_markdown_document(
                (frontmatter_bytes + patched_body).decode("utf-8")
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("patched_source_parse") from exc
        updated_content_hash = context_content_hash(candidate_document.body)
        frontmatter_bytes = _replace_unique_top_level_scalar(
            frontmatter_bytes,
            "content_hash",
            updated_content_hash,
        )
        if current_content_hash != updated_content_hash:
            managed_hash_updated = True

    patched_source = frontmatter_bytes + patched_body
    try:
        patched_document = parse_markdown_document(patched_source.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("patched_source_parse") from exc
    if note_type is AlexandriaNoteType.CONTEXT:
        patched_frontmatter = frontmatter_json(patched_document.frontmatter)
        project_value = patched_frontmatter.get("project")
        status_value = patched_frontmatter.get("status", "active")
        context_identity_from_frontmatter(
            patched_frontmatter,
            project=project_value if isinstance(project_value, str) else None,
            status=status_value if isinstance(status_value, str) else "active",
            generated_content_hash=context_content_hash(patched_document.body),
        )
    return PreparedObsidianBodyPatch(
        source_bytes=patched_source,
        body_replacement_count=len(ordered_spans),
        managed_content_hash_updated=managed_hash_updated,
    )


def _validate_patch_text(value: str) -> None:
    """Reject masked or secret-like caller-supplied replacement text."""
    if "\x00" in value:
        raise ValueError("replacement_control_character")
    if any(placeholder in value for placeholder in _REDACTION_PLACEHOLDERS):
        raise ValueError("replacement_placeholder")
    redaction = redact_secret_text(value)
    if redaction.blocked or redaction.redaction_count > 0:
        raise ValueError("replacement_secret_like")


def _find_all_overlapping(content: bytes, needle: bytes) -> list[int]:
    """Find every occurrence, including overlapping byte matches."""
    matches: list[int] = []
    start = 0
    while True:
        index = content.find(needle, start)
        if index < 0:
            return matches
        matches.append(index)
        if len(matches) == 2:
            return matches
        start = index + 1


def _protected_source_byte_spans(body: str) -> tuple[tuple[int, int], ...]:
    """Find source spans whose existing secret-like bytes must stay untouched."""
    protected_character_spans: list[tuple[int, int]] = []
    for placeholder in _REDACTION_PLACEHOLDERS:
        protected_character_spans.extend(
            (match.start(), match.end())
            for match in re.finditer(re.escape(placeholder), body)
        )

    for pattern in HIGH_RISK_SECRET_PATTERNS:
        protected_character_spans.extend(_high_risk_match_spans(body, pattern))

    for pattern in (
        AUTHORIZATION_HEADER_PATTERN,
        BEARER_TOKEN_PATTERN,
        TOKEN_ASSIGNMENT_PATTERN,
        LONG_TOKEN_PATTERN,
    ):
        protected_character_spans.extend(
            (match.start(), match.end()) for match in pattern.finditer(body)
        )

    protected_character_spans.extend(
        (match.start(), match.end())
        for match in URL_PATTERN.finditer(body)
        if redact_secret_text(match.group(0)).redaction_count > 0
    )

    return tuple(
        (
            len(body[:start].encode("utf-8")),
            len(body[:end].encode("utf-8")),
        )
        for start, end in protected_character_spans
    )


def _high_risk_match_spans(
    body: str, pattern: re.Pattern[str]
) -> list[tuple[int, int]]:
    """Protect only source-owned high-risk spans, including full private-key blocks."""
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(body):
        start, end = match.span()
        if "PRIVATE KEY" in match.group():
            end_match = re.search(
                r"-----END [A-Z ]*PRIVATE KEY-----",
                body[end:],
            )
            if end_match is None:
                end = len(body)
            else:
                end += end_match.end()
        spans.append((start, end))
    return spans


def _map_protected_spans(
    protected_spans: Sequence[tuple[int, int]],
    replacements: Sequence[tuple[int, int, bytes]],
) -> tuple[tuple[int, int], ...]:
    """Map untouched source spans to their expected byte offsets after edits."""
    mapped: list[tuple[int, int]] = []
    for start, end in protected_spans:
        delta = sum(
            len(replacement) - (replacement_end - replacement_start)
            for replacement_start, replacement_end, replacement in replacements
            if replacement_end <= start
        )
        mapped.append((start + delta, end + delta))
    return tuple(mapped)


def _merge_spans(spans: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Normalize overlapping protected spans for exact preservation comparison."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _apply_body_spans(
    body: bytes,
    spans: Sequence[tuple[int, int, bytes]],
) -> bytes:
    """Apply already-validated source offsets without cascading replacements."""
    output: list[bytes] = []
    cursor = 0
    for start, end, replacement in spans:
        output.extend((body[cursor:start], replacement))
        cursor = end
    output.append(body[cursor:])
    return b"".join(output)


def _replace_unique_top_level_scalar(
    frontmatter_bytes: bytes,
    key: str,
    replacement: str,
) -> bytes:
    """Replace one simple scalar token while preserving YAML line bytes."""
    text = frontmatter_bytes.decode("utf-8")
    lines = text.splitlines(keepends=True)
    matches: list[int] = []
    for index, line in enumerate(lines[1:-1], start=1):
        line_content, _line_ending = _split_line_ending(line)
        if line_content[:1].isspace():
            continue
        match = _TOP_LEVEL_KEY_PATTERN.match(line_content)
        if match is not None and match.group("key") == key:
            matches.append(index)
    if len(matches) != 1:
        raise ValueError("managed_content_hash_key_not_unique")

    index = matches[0]
    line_content, line_ending = _split_line_ending(lines[index])
    key_match = re.match(rf"^{re.escape(key)}\s*:\s*", line_content)
    if key_match is None:
        raise ValueError("managed_content_hash_scalar_invalid")
    prefix = key_match.group(0)
    tail = line_content[len(prefix) :]
    leading_space_length = len(tail) - len(tail.lstrip(" \t"))
    leading_space = tail[:leading_space_length]
    scalar_and_suffix = tail[leading_space_length:]
    quote, scalar_end = _scalar_token_end(scalar_and_suffix)
    if scalar_end <= 0:
        raise ValueError("managed_content_hash_scalar_invalid")
    suffix = scalar_and_suffix[scalar_end:]
    if suffix and not re.fullmatch(r"[ \t]+(?:#.*)?", suffix):
        raise ValueError("managed_content_hash_scalar_invalid")
    replacement_token = f"{quote}{replacement}{quote}" if quote else replacement
    lines[index] = f"{prefix}{leading_space}{replacement_token}{suffix}{line_ending}"
    return "".join(lines).encode("utf-8")


def _scalar_token_end(value: str) -> tuple[str, int]:
    """Return the quote style and end offset of one simple YAML scalar token."""
    if not value:
        return "", 0
    quote = value[0] if value[0] in "\"'" else ""
    if quote:
        index = 1
        while index < len(value):
            if quote == '"' and value[index] == "\\":
                index += 2
                continue
            if value[index] == quote:
                if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                return quote, index + 1
            index += 1
        return "", 0

    end = next(
        (index for index, character in enumerate(value) if character in " \t"),
        len(value),
    )
    token = value[:end]
    if not token or token in {"|", ">", "[", "{", "&", "*"}:
        return "", 0
    return "", end


def _split_line_ending(line: str) -> tuple[str, str]:
    """Split one line while retaining LF, CRLF, or CR exactly."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1:]
    return line, ""
