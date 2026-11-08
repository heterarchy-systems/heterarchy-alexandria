"""Typed values that protect caller-owned note writes."""

from enum import StrEnum


class ServerOwnedFrontmatterField(StrEnum):
    """Fields whose persisted values remain owned by the application."""

    CONTENT_HASH = "content_hash"
    INITIAL_CONTENT_HASH = "initial_content_hash"
    PREVIOUS_CONTENT_HASH = "previous_content_hash"
    VERSION = "version"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    LAST_MODIFIED_BY = "last_modified_by"


class RedactionPlaceholder(StrEnum):
    """Masked values that must never be written into canonical Markdown."""

    LONG_VALUE = "<REDACTED_LONG_VALUE>"
    VALUE = "<REDACTED>"
    BLOCKED_SECRET_CONTENT = "[BLOCKED_SECRET_CONTENT]"
