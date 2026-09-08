"""Typed application contracts for durable Obsidian relationships."""

from __future__ import annotations

from dataclasses import dataclass

from app.obsidian.domain.event_enum.obsidian_enums import ObsidianRelationType


@dataclass(frozen=True, slots=True, kw_only=True)
class ObsidianRelateRequest:
    """Request to link two already-existing managed notes."""

    source_note_id: str
    target_note_id: str
    relation: ObsidianRelationType
    idempotency_key: str
    expected_source_hash: str | None = None

    def __post_init__(self) -> None:
        """Reject blank identity and idempotency values before orchestration."""
        if not self.source_note_id.strip():
            raise ValueError("source_note_id must not be blank")
        if not self.target_note_id.strip():
            raise ValueError("target_note_id must not be blank")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        if (
            self.expected_source_hash is not None
            and not self.expected_source_hash.strip()
        ):
            raise ValueError("expected_source_hash must not be blank")
        if self.expected_source_hash is not None:
            normalized_hash = self.expected_source_hash.strip().lower()
            if len(normalized_hash) != 64 or any(
                character not in "0123456789abcdef" for character in normalized_hash
            ):
                raise ValueError(
                    "expected_source_hash must be a SHA-256 hexadecimal digest"
                )
