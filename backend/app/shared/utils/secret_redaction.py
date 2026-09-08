"""Shared secret detection and redaction helpers for persistence boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote_plus

HIGH_RISK_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?im)^\s*\.env\b.*"),
)
BLOCKED_SECRET_PLACEHOLDER = "[BLOCKED_SECRET_CONTENT]"
TOKEN_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*([\"']?)[A-Za-z0-9_./+=:\-]{12,}\2"
)
AUTHORIZATION_HEADER_PATTERN = re.compile(r"(?im)^(\s*authorization\s*:\s*)([^\r\n]+)")
BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer(\s+)[A-Za-z0-9._~+/=-]{4,}")
LONG_TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9+/._=-]{48,}\b")
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
WIKILINK_PATTERN = re.compile(r"\[\[(?P<inner>[^\]\r\n]+)\]\]")
CREDENTIAL_QUERY_PARAMETER_NAMES = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "signature",
        "sig",
        "authorization",
        "auth",
        "password",
        "passwd",
        "session",
        "session_token",
    }
)
SECRET_FIELD_NAME_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential|private[_-]?key)"
)


@dataclass(frozen=True, slots=True)
class SecretRedactionResult:
    """Result returned after secret scanning text content."""

    blocked: bool
    redacted_content: str
    redaction_count: int
    warnings: tuple[str, ...]


def redact_secret_text(content: str) -> SecretRedactionResult:
    """Detect and redact token-like content before long-term storage.

    Args:
        content: Raw text headed toward a persistent boundary.

    Returns:
        SecretRedactionResult: Redaction result and user-facing warnings.
    """
    blocked = any(pattern.search(content) for pattern in HIGH_RISK_SECRET_PATTERNS)
    if blocked:
        return SecretRedactionResult(
            blocked=True,
            redacted_content=BLOCKED_SECRET_PLACEHOLDER,
            redaction_count=1,
            warnings=("high-risk secret content cannot be saved raw",),
        )

    redacted, redaction_count = _redact_text_preserving_urls(content)
    warnings: list[str] = []
    if redaction_count > 0:
        warnings.append("potential secret-like content was redacted")
    return SecretRedactionResult(
        blocked=False,
        redacted_content=redacted,
        redaction_count=redaction_count,
        warnings=tuple(warnings),
    )


def _redact_text_preserving_urls(content: str) -> tuple[str, int]:
    """Redact text preserving urls.

    Args:
        content: Content used by this operation.

    Returns:
        tuple[str, int] result produced by redact text preserving urls.
    """
    redacted_parts: list[str] = []
    redaction_count = 0
    previous_end = 0
    for match in URL_PATTERN.finditer(content):
        text_part, text_count = _redact_non_url_text_preserving_wikilinks(
            content[previous_end : match.start()]
        )
        url, trailing_text = _split_url_trailing_text(match.group(0))
        url_part, url_count = _redact_url_query_credentials(url)
        redacted_parts.extend((text_part, url_part, trailing_text))
        redaction_count += text_count + url_count
        previous_end = match.end()

    text_part, text_count = _redact_non_url_text_preserving_wikilinks(
        content[previous_end:]
    )
    redacted_parts.append(text_part)
    return "".join(redacted_parts), redaction_count + text_count


def _redact_non_url_text_preserving_wikilinks(content: str) -> tuple[str, int]:
    """Redact non url text preserving wikilinks.

    Args:
        content: Content used by this operation.

    Returns:
        tuple[str, int] result produced by redact non url text preserving wikilinks.
    """
    redacted_parts: list[str] = []
    redaction_count = 0
    previous_end = 0
    for match in WIKILINK_PATTERN.finditer(content):
        text_part, text_count = _redact_non_url_text(
            content[previous_end : match.start()]
        )
        wikilink_part, wikilink_count = _redact_wikilink(match.group("inner"))
        redacted_parts.extend((text_part, wikilink_part))
        redaction_count += text_count + wikilink_count
        previous_end = match.end()

    text_part, text_count = _redact_non_url_text(content[previous_end:])
    redacted_parts.append(text_part)
    return "".join(redacted_parts), redaction_count + text_count


def _redact_wikilink(inner: str) -> tuple[str, int]:
    """Redact wikilink.

    Args:
        inner: Inner used by this operation.

    Returns:
        tuple[str, int] result produced by redact wikilink.
    """
    target, separator, label = inner.partition("|")
    redacted_target, target_count = _redact_wikilink_target(target)
    if not separator:
        return f"[[{redacted_target}]]", target_count

    redacted_label, label_count = _redact_non_url_text(label)
    return (
        f"[[{redacted_target}|{redacted_label}]]",
        target_count + label_count,
    )


def _redact_wikilink_target(target: str) -> tuple[str, int]:
    """Redact wikilink target.

    Args:
        target: Target used by this operation.

    Returns:
        tuple[str, int] result produced by redact wikilink target.
    """
    if not _is_internal_wikilink_path(target):
        return _redact_non_url_text(target)

    redacted_segments: list[str] = []
    redaction_count = 0
    for segment in target.split("/"):
        redacted_segment, segment_count = _redact_non_url_text(segment)
        redacted_segments.append(redacted_segment)
        redaction_count += segment_count
    return "/".join(redacted_segments), redaction_count


def _is_internal_wikilink_path(target: str) -> bool:
    """Return whether internal wikilink path.

    Args:
        target: Target used by this operation.

    Returns:
        Whether internal wikilink path.
    """
    candidate = target.strip()
    if (
        not candidate
        or "://" in candidate
        or candidate.startswith("/")
        or "\\" in candidate
    ):
        return False
    path, _fragment_separator, _fragment = candidate.partition("#")
    segments = path.split("/")
    return len(segments) > 1 and all(
        segment.strip() not in {"", ".", ".."} for segment in segments
    )


def _redact_non_url_text(content: str) -> tuple[str, int]:
    """Redact non url text.

    Args:
        content: Content used by this operation.

    Returns:
        tuple[str, int] result produced by redact non url text.
    """
    redacted, authorization_count = AUTHORIZATION_HEADER_PATTERN.subn(
        _redacted_authorization_header,
        content,
    )
    redacted, bearer_count = BEARER_TOKEN_PATTERN.subn(
        lambda match: f"Bearer{match.group(1)}<REDACTED>",
        redacted,
    )
    redacted, assignment_count = TOKEN_ASSIGNMENT_PATTERN.subn(
        lambda match: f"{match.group(1)}=<REDACTED>", redacted
    )
    redacted, token_count = _redact_long_values(redacted)
    return (
        redacted,
        authorization_count + bearer_count + assignment_count + token_count,
    )


def _redact_long_values(content: str) -> tuple[str, int]:
    """Preserve explicitly typed SHA-256 references after credential redaction."""
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        value = match.group(0)
        prefix = content[max(0, match.start() - 7) : match.start()].casefold()
        line_start = content.rfind("\n", 0, match.start()) + 1
        credential_context = is_secret_field_name(content[line_start : match.start()])
        if (
            prefix == "sha256:"
            and not credential_context
            and re.fullmatch(r"[0-9a-fA-F]{64}", value)
        ):
            return value
        count += 1
        return "<REDACTED_LONG_VALUE>"

    return LONG_TOKEN_PATTERN.sub(replace, content), count


def _redacted_authorization_header(match: re.Match[str]) -> str:
    """Execute redacted authorization header.

    Args:
        match: Match used by this operation.

    Returns:
        str result produced by redacted authorization header.
    """
    value = match.group(2).strip()
    scheme, separator, _credential = value.partition(" ")
    if separator and scheme.casefold() in {"basic", "bearer", "digest"}:
        return f"{match.group(1)}{scheme} <REDACTED>"
    return f"{match.group(1)}<REDACTED>"


def _split_url_trailing_text(url: str) -> tuple[str, str]:
    """Split url trailing text.

    Args:
        url: Url used by this operation.

    Returns:
        tuple[str, str] result produced by split url trailing text.
    """
    trailing_start = len(url)
    while trailing_start > 0:
        character = url[trailing_start - 1]
        if character in ".,;:!?":
            trailing_start -= 1
            continue
        opening_character = {")": "(", "]": "[", "}": "{"}.get(character)
        if opening_character is None:
            break
        candidate = url[:trailing_start]
        if candidate.count(character) <= candidate.count(opening_character):
            break
        trailing_start -= 1
    return url[:trailing_start], url[trailing_start:]


def _redact_url_query_credentials(url: str) -> tuple[str, int]:
    """Redact url query credentials.

    Args:
        url: Url used by this operation.

    Returns:
        tuple[str, int] result produced by redact url query credentials.
    """
    url_without_fragment, fragment_separator, fragment = url.partition("#")
    url_path, query_separator, query = url_without_fragment.partition("?")
    redacted_query, query_redaction_count = _redact_url_parameter_values(query)
    redacted_fragment, fragment_redaction_count = _redact_url_parameter_values(fragment)

    redacted_url = url_path
    if query_separator:
        redacted_url = f"{redacted_url}?{redacted_query}"
    if fragment_separator:
        redacted_url = f"{redacted_url}#{redacted_fragment}"
    return redacted_url, query_redaction_count + fragment_redaction_count


def _redact_url_parameter_values(parameters: str) -> tuple[str, int]:
    """Redact url parameter values.

    Args:
        parameters: Parameters used by this operation.

    Returns:
        tuple[str, int] result produced by redact url parameter values.
    """
    parameter_parts = parameters.split("&")
    redaction_count = 0
    for index, parameter_part in enumerate(parameter_parts):
        name, value_separator, value = parameter_part.partition("=")
        normalized_name = unquote_plus(name).lower()
        if (
            value_separator
            and value
            and normalized_name in CREDENTIAL_QUERY_PARAMETER_NAMES
        ):
            parameter_parts[index] = f"{name}=<REDACTED>"
            redaction_count += 1
    return "&".join(parameter_parts), redaction_count


def is_secret_field_name(field_name: str) -> bool:
    """Return whether a structured field name denotes credential material.

    Args:
        field_name: Structured mapping key.

    Returns:
        True when the key denotes credential material.
    """
    return SECRET_FIELD_NAME_PATTERN.search(field_name) is not None
