"""Shared value normalization and evidence serialization for skill artifacts."""

from __future__ import annotations

from collections.abc import Sequence

from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
    SkillAcquisitionEvidenceItem,
)
from app.shared.serialization.orjson_codec import dumps_pretty_json
from app.shared.types.extra_types import JSONObject, JSONValue


def _bullet_or_none(items: list[str]) -> str:
    if not items:
        return "- none provided"
    return "\n".join(f"- {item}" for item in items)


def _clean_items(values: Sequence[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _json_block(value: JSONValue) -> str:
    return "```json\n" + dumps_pretty_json(value).decode("utf-8") + "\n```"


def _evidence_item_payloads(artifact: SkillAcquisitionArtifact) -> list[JSONObject]:
    structured = [
        _evidence_item_payload(item=item, default_title=artifact.title)
        for item in artifact.evidence_items
        if item.url_or_path.strip()
    ]
    if structured:
        return structured
    return [
        {
            "url_or_path": url,
            "title": artifact.title,
            "source_kind": "source",
            "publisher_or_repository": None,
            "accessed_at": None,
            "supports_claims": [artifact.source_summary or artifact.purpose],
            "freshness": None,
            "notes": None,
        }
        for url in _clean_items(artifact.evidence_urls)
    ]


def _evidence_item_payload(
    item: SkillAcquisitionEvidenceItem,
    default_title: str,
) -> JSONObject:
    return {
        "url_or_path": item.url_or_path.strip(),
        "title": _clean_optional(item.title) or default_title,
        "source_kind": _clean_optional(item.source_kind) or "source",
        "publisher_or_repository": _clean_optional(item.publisher_or_repository),
        "accessed_at": _clean_optional(item.accessed_at),
        "supports_claims": _clean_items(item.supports_claims),
        "freshness": _clean_optional(item.freshness),
        "notes": _clean_optional(item.notes),
    }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
