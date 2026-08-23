"""Row cleanup helpers for the Obsidian rebuildable index cache."""

from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianEdgeORM,
    ObsidianFileORM,
)


async def get_obsidian_file_by_path(
    session: AsyncSession,
    relative_path: str,
) -> ObsidianFileORM | None:
    """Read one indexed Obsidian file row by vault-relative path.

    Args:
        session: Active database session.
        relative_path: Vault-relative Markdown path.

    Returns:
        Matching file row, or ``None`` when absent.
    """
    row = await session.execute(
        select(ObsidianFileORM).where(ObsidianFileORM.relative_path == relative_path)
    )
    return row.scalar_one_or_none()


async def discard_obsidian_note_index(session: AsyncSession, note_id: str) -> None:
    """Remove dependent cache rows for one indexed Obsidian note id.

    Args:
        session: Active database session.
        note_id: Stable note id whose index rows should be discarded.

    Returns:
        None.
    """
    await session.execute(
        delete(ObsidianChunkORM).where(ObsidianChunkORM.note_id == note_id)
    )
    await session.execute(
        delete(ObsidianEdgeORM).where(
            or_(
                ObsidianEdgeORM.source_note_id == note_id,
                ObsidianEdgeORM.target_note_id == note_id,
            )
        )
    )
