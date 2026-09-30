"""Authoritative source evidence acquisition for Memory Compact review."""

from __future__ import annotations

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactSourceObservation,
    MemoryCompactSourceReader,
)
from app.memory.domain.entities.memory_compact import MemoryCompact


async def read_current_source_observations(
    compact: MemoryCompact,
    source_reader: MemoryCompactSourceReader | None,
) -> tuple[MemoryCompactSourceObservation, ...]:
    """Read every compact source through the owning source reader.

    Args:
        compact: Compact whose canonical source references must be checked.
        source_reader: Injected reader for Obsidian, Context, and Compact sources.

    Returns:
        One observation for each source reference, preserving source order.

    Raises:
        ValueError: When a reader returns evidence for a different source.
    """
    if source_reader is None:
        return tuple(
            MemoryCompactSourceObservation(
                source_id=ref.source_id,
                detail_path=ref.detail_path,
                available=False,
                unavailable_reason="source_reader_not_configured",
            )
            for ref in compact.source_refs
        )
    observations: list[MemoryCompactSourceObservation] = []
    for source_ref in compact.source_refs:
        try:
            observation = await source_reader(source_ref)
        except Exception as exc:
            observation = MemoryCompactSourceObservation(
                source_id=source_ref.source_id,
                detail_path=source_ref.detail_path,
                available=False,
                unavailable_reason=type(exc).__name__,
            )
        if observation.source_id != source_ref.source_id:
            raise ValueError(
                "Memory Compact source reader returned a different source identity"
            )
        if (
            observation.detail_path is not None
            and observation.detail_path != source_ref.detail_path
        ):
            raise ValueError(
                "Memory Compact source reader returned a different source path"
            )
        observations.append(observation)
    return tuple(observations)


__all__ = ("read_current_source_observations",)
