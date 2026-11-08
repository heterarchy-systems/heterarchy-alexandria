"""Same-transaction writer for the durable Context change log.

Every call must run on the caller's active mutation session so the change
record commits (or rolls back) together with the Context mutation it
describes; the sequence allocator advances inside that same transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.event_enum.context_enums import ContextChangeKind
from app.memory.infrastructure.models.context_models import (
    ContextChangeLogMetaORM,
    ContextChangeLogORM,
)
from app.shared.compute.native_text_hashing import hash_text


def context_change_content_hash(content: str) -> bytes:
    """Return the post-change content hash for one Context row.

    Args:
        content: Stored Context content text.

    Returns:
        32-byte SHA-256 digest from the canonical native hasher.
    """
    return bytes.fromhex(hash_text(content))


async def record_context_change(
    session: AsyncSession,
    *,
    context_id: str,
    change_kind: ContextChangeKind,
    content_hash: bytes,
    recorded_at: datetime,
) -> None:
    """Append one change record inside the caller's active transaction.

    Args:
        session: Active async session owning the surrounding mutation tx.
        context_id: Identifier of the mutated Context row.
        change_kind: Recorded mutation kind.
        content_hash: Post-change content digest.
        recorded_at: Mutation timestamp shared with the mutated row.
    """
    await session.execute(
        pg_insert(ContextChangeLogMetaORM)
        .values(singleton_id=1, high_water_seq=0)
        .on_conflict_do_nothing(index_elements=[ContextChangeLogMetaORM.singleton_id])
    )
    allocated = await session.execute(
        update(ContextChangeLogMetaORM)
        .where(ContextChangeLogMetaORM.singleton_id == 1)
        .values(high_water_seq=ContextChangeLogMetaORM.high_water_seq + 1)
        .returning(ContextChangeLogMetaORM.high_water_seq)
    )
    session.add(
        ContextChangeLogORM(
            sequence=allocated.scalar_one(),
            context_id=context_id,
            change_kind=change_kind.value,
            content_hash=content_hash,
            recorded_at=recorded_at,
        )
    )
    await session.flush()
