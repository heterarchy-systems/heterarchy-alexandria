"""Stable Memory Compact duplicate-detection signatures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)
from app.shared.types.types_convert_utils import aware_utc_datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRefSignature:
    """Stable source-ref key used for duplicate detection."""

    source_type: str
    source_id: str
    detail_path: str
    source_hash: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCompactSignature:
    """Stable signature for a Memory Compact candidate."""

    project: str | None
    covered_from: datetime
    covered_to: datetime
    source_refs: tuple[SourceRefSignature, ...]
    body_hash: str


def create_signature(payload: MemoryCompactCreate) -> MemoryCompactSignature:
    """Build the duplicate-detection signature for a creation payload.

    Args:
        payload: Normalized Memory Compact creation contract.

    Returns:
        Stable candidate signature.
    """
    return MemoryCompactSignature(
        project=payload.project,
        covered_from=aware_utc_datetime(payload.covered_from),
        covered_to=aware_utc_datetime(payload.covered_to),
        source_refs=tuple(
            sorted(
                (
                    SourceRefSignature(
                        source_type=source_ref.source_type,
                        source_id=source_ref.source_id,
                        detail_path=source_ref.detail_path,
                        source_hash=source_ref.source_hash,
                    )
                    for source_ref in payload.source_refs
                ),
                key=_source_ref_sort_key,
            )
        ),
        body_hash=_body_hash(payload.markdown_body),
    )


def compact_signature(compact: MemoryCompact) -> MemoryCompactSignature:
    """Build the duplicate-detection signature for a stored compact.

    Args:
        compact: Stored Memory Compact entity.

    Returns:
        Stable stored signature.
    """
    return MemoryCompactSignature(
        project=compact.project,
        covered_from=aware_utc_datetime(compact.covered_from),
        covered_to=aware_utc_datetime(compact.covered_to),
        source_refs=tuple(
            sorted(
                (
                    SourceRefSignature(
                        source_type=source_ref.source_type,
                        source_id=source_ref.source_id,
                        detail_path=source_ref.detail_path,
                        source_hash=source_ref.source_hash,
                    )
                    for source_ref in compact.source_refs
                ),
                key=_source_ref_sort_key,
            )
        ),
        body_hash=_body_hash(compact.markdown_body),
    )


def _source_ref_sort_key(
    source_ref: SourceRefSignature,
) -> tuple[str, str, str, str]:
    return (
        source_ref.source_type,
        source_ref.source_id,
        source_ref.detail_path,
        source_ref.source_hash or "",
    )


def _body_hash(markdown_body: str) -> str:
    return sha256(markdown_body.strip().encode("utf-8")).hexdigest()
