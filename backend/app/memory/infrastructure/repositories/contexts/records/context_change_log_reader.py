"""Read-only bounded delta reads over the durable Context change log.

Reads never write: delta queries allocate no sequences and insert no rows.
Ordering is by the global ``sequence`` column only; ``recorded_at`` is
metadata and never participates in ordering. Because the high-water sequence
advances only inside the transaction that inserts the matching change row,
a committed cursor can never point past a committed change (no gap can hide
undelivered entries); sequences left unused by rolled-back transactions are
skipped without breaking the ordering contract.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.entities.context_change_log import (
    ContextChangeEntry,
    ContextDeltaPage,
)
from app.memory.domain.types.context_change_cursor import (
    ContextChangeCursor,
    decode_context_change_cursor,
    encode_context_change_cursor,
)
from app.memory.infrastructure.models.context_models import ContextChangeLogORM
from app.shared.serialization.orjson_codec import dumps_json

MAX_CONTEXT_DELTA_ROWS = 64

# Backstop byte budget for one delta page. Entries are small identity records
# (sequence, id, kind, hash, timestamp); at the 64-row cap a page serializes to
# well under 16 KiB, so this budget only guards against pathological growth.
_MAX_CONTEXT_DELTA_RESPONSE_BYTES = 262_144


async def read_context_delta(
    session: AsyncSession,
    *,
    cursor_token: str | None,
    max_rows: int,
) -> ContextDeltaPage:
    """Return one bounded, sequence-ordered delta page.

    Args:
        session: Read-only async session.
        cursor_token: Opaque cursor from a previous page, or None for a fresh
            read starting at the beginning of the log.
        max_rows: Maximum entries for this page (1..MAX_CONTEXT_DELTA_ROWS).

    Returns:
        Delta page with entries, next opaque cursor, and has-more flag.
    """
    cursor = (
        decode_context_change_cursor(cursor_token)
        if cursor_token is not None
        else ContextChangeCursor(last_sequence=0)
    )
    rows = (
        (
            await session.execute(
                select(ContextChangeLogORM)
                .where(ContextChangeLogORM.sequence > cursor.last_sequence)
                .order_by(ContextChangeLogORM.sequence)
                .limit(max_rows + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > max_rows
    entries: list[ContextChangeEntry] = []
    last_sequence = cursor.last_sequence
    response_bytes = 0
    for row in rows[:max_rows]:
        entry_bytes = _entry_wire_bytes(row)
        if entries and response_bytes + entry_bytes > _MAX_CONTEXT_DELTA_RESPONSE_BYTES:
            has_more = True
            break
        entries.append(_entry_from_row(row))
        last_sequence = row.sequence
        response_bytes += entry_bytes
    return ContextDeltaPage(
        entries=tuple(entries),
        next_cursor=encode_context_change_cursor(last_sequence),
        has_more=has_more,
    )


def _entry_from_row(row: ContextChangeLogORM) -> ContextChangeEntry:
    """Map one change-log ORM row to its read-model entry.

    Args:
        row: Change-log ORM row.

    Returns:
        Context change entry read model.
    """
    return ContextChangeEntry(
        sequence=row.sequence,
        context_id=row.context_id,
        change_kind=row.change_kind,
        content_hash=row.content_hash,
        recorded_at=row.recorded_at,
    )


def _entry_wire_bytes(row: ContextChangeLogORM) -> int:
    """Return the serialized wire size of one entry payload.

    Args:
        row: Change-log ORM row.

    Returns:
        Serialized JSON byte count for the entry payload.
    """
    return len(
        dumps_json(
            {
                "sequence": row.sequence,
                "context_id": row.context_id,
                "change_kind": row.change_kind,
                "content_hash": row.content_hash.hex(),
                "recorded_at": row.recorded_at.isoformat(),
            }
        )
    )
