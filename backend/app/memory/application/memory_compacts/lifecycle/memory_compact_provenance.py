"""Deterministic provenance seal for Memory Compact 2.0 artifacts."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol, cast

from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONValue

MEMORY_COMPACT_POLICY_VERSION = "memory-compact-v2"
MEMORY_COMPACT_GENERATION_REVISION = 1


# protocol-contract: structural-seam
class MemoryCompactSourceIdentity(Protocol):
    """Minimal source-reference shape required for provenance hashing."""

    @property
    def source_type(self) -> str:
        """Return the compact source category used in provenance hashing.

        Returns:
            Stable source category string.
        """
        ...

    @property
    def source_id(self) -> str:
        """Return the stable source identity used in provenance hashing.

        Returns:
            Stable source identifier.
        """
        ...

    @property
    def detail_path(self) -> str:
        """Return the canonical expansion path for the compact source.

        Returns:
            Canonical source detail path.
        """
        ...

    @property
    def source_hash(self) -> str | None:
        """Return the optional source content hash used in provenance sealing.

        Returns:
            Source content hash when available; otherwise None.
        """
        ...


def memory_compact_source_set_hash(
    source_refs: tuple[MemoryCompactSourceIdentity, ...],
) -> str:
    """Return an order-independent deterministic hash for one compact source set.

    Args:
        source_refs: Source references with identity, expansion path, and source hash.

    Returns:
        Lowercase SHA-256 hex digest over the canonical sorted source-set payload.
    """
    payload = [
        {
            "source_type": source_ref.source_type,
            "source_id": source_ref.source_id,
            "detail_path": source_ref.detail_path,
            "source_hash": source_ref.source_hash,
        }
        for source_ref in sorted(
            source_refs,
            key=lambda item: (
                item.source_type,
                item.source_id,
                item.detail_path,
                item.source_hash or "",
            ),
        )
    ]
    return sha256(dumps_canonical_json(cast(JSONValue, payload))).hexdigest()
