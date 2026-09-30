"""Independent canonical source evidence fixtures for Memory Compact tests."""

from __future__ import annotations

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactSourceObservation,
)
from app.memory.domain.entities.memory_compact import MemoryCompactSourceRef

_DEFAULT_SOURCE_HASHES = {
    "ctx-1": "fixture-hash:ctx-1",
    "ctx-2": "fixture-hash:ctx-2",
    "ctx-a": "fixture-hash:ctx-a",
    "ctx-b": "fixture-hash:ctx-b",
    "ctx-default": "fixture-hash:ctx-default",
    "ctx-duplicate": "fixture-hash:ctx-duplicate",
    "ctx-evidence-link": "fixture-hash:ctx-evidence-link",
    "ctx-hash": "hash-before",
    "ctx-new": "fixture-hash:ctx-new",
    "ctx-project-a-2": "fixture-hash:ctx-project-a-2",
    "ctx-project-b": "fixture-hash:ctx-project-b",
    "ctx-unique": "fixture-hash:ctx-unique",
    "ctx-broken": "fixture-hash:ctx-broken",
    "ctx-may": "fixture-hash:ctx-may",
    "ctx-june": "fixture-hash:ctx-june",
    "ctx-blank-source-type": "fixture-hash:ctx-blank-source-type",
    "ctx-source": "fixture-hash:ctx-source",
    "ctx-storage": "fixture-hash:ctx-storage",
}


class DeterministicCompactSourceReader:
    """Return fixture-owned source evidence without echoing request hashes."""

    def __init__(self, source_hashes: dict[str, str] | None = None) -> None:
        self._source_hashes = dict(_DEFAULT_SOURCE_HASHES)
        self._source_hashes.update(source_hashes or {})

    async def __call__(
        self,
        source: MemoryCompactSourceRef,
    ) -> MemoryCompactSourceObservation:
        current_hash = self._source_hashes.get(source.source_id)
        if current_hash is None:
            return MemoryCompactSourceObservation(
                source_id=source.source_id,
                detail_path=source.detail_path,
                available=False,
                unavailable_reason="fixture_source_missing",
                source_revision=None,
            )
        return MemoryCompactSourceObservation(
            source_id=source.source_id,
            detail_path=source.detail_path,
            current_source_hash=current_hash,
            source_revision=f"fixture-revision:{source.source_id}",
        )
