"""Secret redaction helpers for Obsidian frontmatter payloads."""

from __future__ import annotations

import re

from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.types.extra_types import JSONObject, JSONValue
from app.shared.utils.secret_redaction import (
    is_secret_field_name,
    redact_secret_text,
)

_FRONTMATTER_KEY_PATTERN = re.compile(r"^\s*(?:-\s*)?([^:#][^:]*)\s*:")
_FALSE_SECRET_AUDIT_FIELDS = frozenset({"secret_values_recorded"})


def redacted_frontmatter(frontmatter: JSONObject) -> tuple[JSONObject, list[str]]:
    """Return frontmatter with string values redacted before persistence.

    Args:
        frontmatter: Caller-provided frontmatter object.

    Returns:
        Redacted frontmatter and user-facing warnings.
    """
    redacted, warnings = _redacted_json(frontmatter)
    return dict(redacted) if isinstance(redacted, dict) else {}, warnings


def frontmatter_contains_secret_field(markdown: str) -> bool:
    """Return whether raw YAML frontmatter declares a secret-like key.

    Args:
        markdown: Complete Markdown document.

    Returns:
        True when frontmatter contains a credential-like field name.
    """
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        match = _FRONTMATTER_KEY_PATTERN.match(line)
        if match is None:
            continue
        field_name = match.group(1).strip()
        if not is_secret_field_name(field_name):
            continue
        raw_value = line[match.end() :].strip()
        if _is_safe_false_secret_audit_field(field_name, raw_value):
            continue
        return True
    return False


def _redacted_json(value: JSONValue) -> tuple[JSONValue, list[str]]:
    if isinstance(value, str):
        redaction = redact_secret_text(value)
        if redaction.blocked:
            raise ObsidianValidationError(
                "high-risk secret content cannot be saved in frontmatter"
            )
        return redaction.redacted_content, list(redaction.warnings)
    if isinstance(value, list | tuple):
        return _redacted_sequence(value)
    if isinstance(value, dict):
        return _redacted_mapping(value)
    return value, []


def _redacted_sequence(
    value: list[JSONValue] | tuple[JSONValue, ...],
) -> tuple[
    list[JSONValue],
    list[str],
]:
    items: list[JSONValue] = []
    warnings: list[str] = []
    for item in value:
        redacted_item, item_warnings = _redacted_json(item)
        items.append(redacted_item)
        warnings.extend(item_warnings)
    return items, _dedupe_warnings(warnings)


def _redacted_mapping(value: dict[str, JSONValue]) -> tuple[JSONObject, list[str]]:
    payload: JSONObject = {}
    warnings: list[str] = []
    for key, item in value.items():
        field_name = str(key)
        if _is_safe_false_secret_audit_field(field_name, item):
            payload[field_name] = False
            continue
        if is_secret_field_name(field_name) and item not in (None, ""):
            warnings.append("potential secret-like frontmatter field was redacted")
            continue
        redacted_item, item_warnings = _redacted_json(item)
        payload[field_name] = redacted_item
        warnings.extend(item_warnings)
    return payload, _dedupe_warnings(warnings)


def _is_safe_false_secret_audit_field(
    field_name: str,
    value: JSONValue,
) -> bool:
    if field_name.casefold() not in _FALSE_SECRET_AUDIT_FIELDS:
        return False
    if value is False:
        return True
    return isinstance(value, str) and value.casefold() == "false"


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    deduped: list[str] = []
    for warning in warnings:
        if warning not in deduped:
            deduped.append(warning)
    return deduped
