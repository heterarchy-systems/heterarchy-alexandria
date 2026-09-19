"""Canonical Context change-log recorder adapter for the Obsidian index write.

The Obsidian index write store accepts a structural change recorder and
invokes it inside the same transaction that commits each canonical note
projection. This adapter is the memory-owned implementation of that seam: it
maps the write-store's observed transition onto the durable Context change
log so canonical create/update/supersede (and archive) transitions land in
the log in the transaction that makes them PG-observed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.event_enum.context_enums import ContextChangeKind
from app.memory.infrastructure.repositories.contexts.records.context_change_log_writer import (
    record_context_change,
)

_CHANGE_KINDS: dict[str, ContextChangeKind] = {
    item.value: item for item in ContextChangeKind
}


async def record_obsidian_context_change(
    session: AsyncSession,
    *,
    context_id: str,
    change_kind: str,
    content_hash: bytes,
    recorded_at: datetime,
) -> None:
    """Append one canonical Context change record on the caller's session.

    Args:
        session: Active async session owning the surrounding index-write tx.
        context_id: Canonical note identifier of the changed Context.
        change_kind: Observed transition kind reported by the write store.
        content_hash: Post-change content digest.
        recorded_at: Mutation timestamp shared with the indexed note.

    Raises:
        ValueError: When the reported kind is not a known change kind.
    """
    kind = _CHANGE_KINDS.get(change_kind)
    if kind is None:
        raise ValueError(f"Unknown canonical Context change kind: {change_kind}")
    await record_context_change(
        session,
        context_id=context_id,
        change_kind=kind,
        content_hash=content_hash,
        recorded_at=recorded_at,
    )
