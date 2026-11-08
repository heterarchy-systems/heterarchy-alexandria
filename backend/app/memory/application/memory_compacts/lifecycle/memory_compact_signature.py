"""Stable Memory Compact duplicate-detection signatures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactSourceObservation,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject
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
                key=_CompactSignaturePayload.source_ref_sort_key,
            )
        ),
        body_hash=body_hash(payload.markdown_body),
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
                key=_CompactSignaturePayload.source_ref_sort_key,
            )
        ),
        body_hash=body_hash(compact.markdown_body),
    )


def reviewed_compact_hash(
    compact: MemoryCompact,
    *,
    verdict: str,
    total_score: int,
    max_score: int,
    source_observations: tuple[MemoryCompactSourceObservation, ...] = (),
) -> str:
    """Bind one review receipt to the exact reviewed body.

    Args:
        compact: Reviewed compact whose durable body is bound.
        verdict: Review verdict value.
        total_score: Review total score.
        max_score: Review maximum score.
        source_observations: Current source evidence used by the review.

    Returns:
        Deterministic hash over body hash and review outcome.
    """
    payload: JSONObject = {
        "compact_state": _CompactSignaturePayload.compact_state_payload(compact),
        "verdict": verdict,
        "total_score": total_score,
        "max_score": max_score,
        "source_observations": [
            {
                "source_id": observation.source_id,
                "source_revision": observation.source_revision,
                "source_scope": observation.source_scope,
                "source_visibility": observation.source_visibility,
                "detail_path": observation.detail_path,
                "current_source_hash": observation.current_source_hash,
                "available": observation.available,
                "unavailable_reason": observation.unavailable_reason,
            }
            for observation in source_observations
        ],
    }
    return sha256(dumps_pretty_json(payload)).hexdigest()


def compact_state_hash(compact: MemoryCompact) -> str:
    """Hash the exact state admitted for CURRENT promotion.

    Args:
        compact: Candidate compact read before persistence.

    Returns:
        Deterministic hash over promotion-relevant compact state.
    """
    return sha256(
        dumps_pretty_json(_CompactSignaturePayload.compact_state_payload(compact))
    ).hexdigest()


class _CompactSignaturePayload:
    """Serialize deterministic payloads and sort keys for compact signatures."""

    @staticmethod
    def source_ref_sort_key(
        source_ref: SourceRefSignature,
    ) -> tuple[str, str, str, str]:
        """Return a deterministic sort key for a source reference signature.

        Args:
            source_ref: Source reference signature to order.

        Returns:
            Tuple of source type, id, detail path, and normalized source hash.
        """
        return (
            source_ref.source_type,
            source_ref.source_id,
            source_ref.detail_path,
            source_ref.source_hash or "",
        )

    @staticmethod
    def compact_state_payload(compact: MemoryCompact) -> JSONObject:
        """Build the promotion-relevant compact state payload.

        Args:
            compact: Candidate compact entity to serialize.

        Returns:
            JSON object of promotion-relevant compact fields.
        """
        return {
            "id": compact.id,
            "project": compact.project,
            "covered_from": aware_utc_datetime(compact.covered_from).isoformat(),
            "covered_to": aware_utc_datetime(compact.covered_to).isoformat(),
            "status": compact.status.value,
            "body": compact.markdown_body,
            "source_refs": [
                {
                    "id": source_ref.id,
                    "compact_id": source_ref.compact_id,
                    "source_type": source_ref.source_type,
                    "source_id": source_ref.source_id,
                    "title": source_ref.title,
                    "detail_path": source_ref.detail_path,
                    "source_hash": source_ref.source_hash,
                }
                for source_ref in compact.source_refs
            ],
        }


def body_hash(markdown_body: str) -> str:
    """Compute the SHA-256 hex digest of a normalized compact Markdown body.

    Args:
        markdown_body: Compact Markdown body text.

    Returns:
        Hex-encoded SHA-256 digest of the stripped Markdown body.
    """
    return sha256(markdown_body.strip().encode("utf-8")).hexdigest()
