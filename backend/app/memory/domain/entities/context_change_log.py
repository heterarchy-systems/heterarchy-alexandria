"""Durable Context Vault change-log read models for bounded delta reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ContextChangeEntry:
    """One recorded Context mutation identity record."""

    sequence: int
    context_id: str
    change_kind: str
    content_hash: bytes
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ContextDeltaPage:
    """One bounded delta page over the durable Context change log."""

    entries: tuple[ContextChangeEntry, ...]
    next_cursor: str
    has_more: bool
