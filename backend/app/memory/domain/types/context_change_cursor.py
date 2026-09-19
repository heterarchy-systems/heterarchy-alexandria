"""Opaque versioned cursor tokens for bounded Context change-log delta reads.

The token is URL-safe base64 of a compact JSON object::

    {"v": 1, "scope": "context-change-log", "last_sequence": <int>}

The ``scope`` field binds the token to one change-log identity and the ``v``
field to one token format. Malformed or structurally unknown tokens raise
:class:`ContextChangeCursorInvalidError`; structurally valid tokens carrying a
different version or scope raise
:class:`ContextChangeCursorResyncRequiredError` so stale or foreign cursors are
rejected explicitly instead of being silently accepted.

The log uses one global sequence (caller-visible ordering), so sequences are
unique across every caller scope; scope identity travels only in the cursor.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from json import dumps, loads
from typing import Final

from app.shared.exceptions.memory_context_exceptions import (
    ContextChangeCursorInvalidError,
    ContextChangeCursorResyncRequiredError,
)

CONTEXT_CHANGE_CURSOR_VERSION: Final[int] = 1
CONTEXT_CHANGE_LOG_SCOPE: Final[str] = "context-change-log"
_CURSOR_KEYS: Final[frozenset[str]] = frozenset({"v", "scope", "last_sequence"})


@dataclass(frozen=True, slots=True)
class ContextChangeCursor:
    """Decoded change-log cursor state."""

    last_sequence: int


def encode_context_change_cursor(last_sequence: int) -> str:
    """Encode one cursor state as an opaque token.

    Args:
        last_sequence: Last delivered change-log sequence (0 for a fresh read).

    Returns:
        URL-safe base64 cursor token.
    """
    payload = {
        "v": CONTEXT_CHANGE_CURSOR_VERSION,
        "scope": CONTEXT_CHANGE_LOG_SCOPE,
        "last_sequence": last_sequence,
    }
    return urlsafe_b64encode(
        dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def decode_context_change_cursor(token: str) -> ContextChangeCursor:
    """Decode one opaque cursor token.

    Args:
        token: Cursor token previously returned by a delta read.

    Returns:
        Decoded cursor state.

    Raises:
        ContextChangeCursorInvalidError: When the token is not decodable
            base64, not a JSON object, or has an unknown structure.
        ContextChangeCursorResyncRequiredError: When the token is structurally
            valid but carries an unsupported format version or foreign scope.
    """
    try:
        raw = urlsafe_b64decode(token.encode("ascii"))
        payload = loads(raw)
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise ContextChangeCursorInvalidError(
            "Change-log cursor token is not decodable"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _CURSOR_KEYS:
        raise ContextChangeCursorInvalidError(
            "Change-log cursor token has an unknown structure"
        )
    version = payload["v"]
    scope = payload["scope"]
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or not isinstance(scope, str)
    ):
        raise ContextChangeCursorInvalidError(
            "Change-log cursor token has unknown field types"
        )
    if version != CONTEXT_CHANGE_CURSOR_VERSION or scope != CONTEXT_CHANGE_LOG_SCOPE:
        raise ContextChangeCursorResyncRequiredError(
            "Change-log cursor version or scope does not match this log; "
            "a full resynchronization is required"
        )
    last_sequence = payload["last_sequence"]
    if not isinstance(last_sequence, int) or isinstance(last_sequence, bool):
        raise ContextChangeCursorInvalidError(
            "Change-log cursor token has an unknown last_sequence type"
        )
    if last_sequence < 0:
        raise ContextChangeCursorInvalidError(
            "Change-log cursor token has a negative last_sequence"
        )
    return ContextChangeCursor(last_sequence=last_sequence)
