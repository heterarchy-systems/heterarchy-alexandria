"""Stable fingerprint metadata for embedding generation strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True)
class EmbeddingFingerprint:
    """Stable identity for one embedding generation strategy."""

    provider: str
    model: str
    provider_version: str
    pooling_mode: str
    normalize: bool
    dimensions: int
    document_input_format: str

    def identity_payload(self) -> JSONObject:
        """Return the timestamp-free identity payload.

        Returns:
            JSON-compatible embedding identity metadata.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "provider_version": self.provider_version,
            "pooling_mode": self.pooling_mode,
            "normalize": self.normalize,
            "dimensions": self.dimensions,
            "document_input_format": self.document_input_format,
        }

    def key(self) -> str:
        """Return a deterministic key for equality comparisons.

        Returns:
            Stable JSON key excluding generated/index timestamps.
        """
        return dumps_canonical_json(self.identity_payload()).decode("utf-8")

    def snapshot_payload(self, indexed_at: datetime) -> JSONObject:
        """Return persisted fingerprint metadata for one generated embedding.

        Args:
            indexed_at: Timestamp when the embedding was generated and stored.

        Returns:
            JSON-compatible fingerprint snapshot.
        """
        payload = self.identity_payload()
        timestamp = indexed_at.isoformat()
        payload["generated_at"] = timestamp
        payload["indexed_at"] = timestamp
        return payload
