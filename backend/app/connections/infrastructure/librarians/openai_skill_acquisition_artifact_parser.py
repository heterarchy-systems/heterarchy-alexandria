"""Parse OpenAI/Codex skill-acquisition provider responses."""

from __future__ import annotations

import re

from app.librarian.domain.contracts.skill_acquisition_contracts import (
    SkillAcquisitionArtifact,
    SkillAcquisitionEvidenceItem,
)
from app.librarian.domain.event_enum.skill_acquisition_enums import (
    ItemStatus,
    RiskLevel,
)
from app.shared.exceptions.librarian_exceptions import (
    LibrarianSkillAcquisitionArtifactError,
)
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONValue

_JSON_BLOCK = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def skill_acquisition_artifact_from_provider_text(
    response_text: str,
) -> SkillAcquisitionArtifact:
    """Parse a strict JSON provider response into an acquisition artifact.

    Args:
        response_text: Raw provider text response.

    Returns:
        Validated skill-acquisition artifact.
    """
    payload = _artifact_payload(response_text)
    return SkillAcquisitionArtifact(
        title=_required_text(payload, "title"),
        purpose=_required_text(payload, "purpose"),
        content=_required_text(payload, "content"),
        summary=_optional_text(payload, "summary"),
        category_id=_optional_text(payload, "category_id", strip=False),
        tags=tuple(_string_list(payload, "tags")),
        required_tools=tuple(_string_list(payload, "required_tools")),
        evidence_urls=tuple(_string_list(payload, "evidence_urls")),
        evidence_items=tuple(_evidence_items(payload)),
        risk_level=_risk_level(payload.get("risk_level")),
        version=_optional_text(payload, "version") or "1.0.0",
        created_by_name=_optional_text(payload, "created_by_name", strip=False),
        activate=_coerce_bool(payload.get("activate")),
        status=_item_status(payload.get("status")),
        source_summary=_optional_text(payload, "source_summary"),
        next_steps=tuple(_string_list(payload, "next_steps")),
    )


def _artifact_payload(summary: str) -> dict[str, JSONValue]:
    if not summary.strip():
        raise LibrarianSkillAcquisitionArtifactError(
            "Provider returned an empty response"
        )
    payload_text = _strip_markdown_fences(summary)
    try:
        raw_payload = loads_json(payload_text)
    except (TypeError, ValueError) as error:
        raise LibrarianSkillAcquisitionArtifactError(
            "Provider response must be strict JSON"
        ) from error
    if not isinstance(raw_payload, dict):
        raise LibrarianSkillAcquisitionArtifactError(
            "Provider response must be a JSON object"
        )
    return raw_payload


def _evidence_items(
    payload: dict[str, JSONValue],
) -> list[SkillAcquisitionEvidenceItem]:
    value = payload.get("evidence_items")
    if value is None:
        return []
    if not isinstance(value, list):
        raise LibrarianSkillAcquisitionArtifactError("evidence_items must be a list")
    items: list[SkillAcquisitionEvidenceItem] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise LibrarianSkillAcquisitionArtifactError(
                "evidence_items must be objects"
            )
        item = SkillAcquisitionEvidenceItem(
            url_or_path=_required_text(entry, "url_or_path"),
            title=_optional_text(entry, "title"),
            source_kind=_optional_text(entry, "source_kind"),
            publisher_or_repository=_optional_text(entry, "publisher_or_repository"),
            accessed_at=_optional_text(entry, "accessed_at"),
            supports_claims=tuple(_string_list(entry, "supports_claims")),
            freshness=_optional_text(entry, "freshness"),
            notes=_optional_text(entry, "notes"),
        )
        items.append(item)
    return items


def _string_list(payload: dict[str, JSONValue], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise LibrarianSkillAcquisitionArtifactError(f"{key} must be a list")
    text_values: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise LibrarianSkillAcquisitionArtifactError(
                f"{key} must be text values only"
            )
        stripped = entry.strip()
        if stripped:
            text_values.append(stripped)
    return text_values


def _required_text(payload: dict[str, JSONValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise LibrarianSkillAcquisitionArtifactError(f"{key} is required")
    text = value.strip()
    if not text:
        raise LibrarianSkillAcquisitionArtifactError(f"{key} is required")
    return text


def _optional_text(
    payload: dict[str, JSONValue],
    key: str,
    strip: bool = True,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LibrarianSkillAcquisitionArtifactError(f"{key} must be text")
    text = value.strip() if strip else value
    if strip:
        return text if text else None
    return text


def _coerce_bool(value: JSONValue | None) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise LibrarianSkillAcquisitionArtifactError("activate must be true or false")
    return value


def _risk_level(value: JSONValue | None) -> RiskLevel:
    if value is None:
        return RiskLevel.LOW
    if not isinstance(value, str):
        raise LibrarianSkillAcquisitionArtifactError(
            "risk_level must be LOW/MEDIUM/HIGH"
        )
    try:
        return RiskLevel(value.strip())
    except ValueError as error:
        raise LibrarianSkillAcquisitionArtifactError(
            "risk_level must be LOW/MEDIUM/HIGH"
        ) from error


def _item_status(value: JSONValue | None) -> ItemStatus:
    if value is None:
        return ItemStatus.DRAFT
    if not isinstance(value, str):
        raise LibrarianSkillAcquisitionArtifactError(
            "status must be ACTIVE/NEEDS_REVIEW/DRAFT/ARCHIVED/DEPRECATED/SUPERSEDED"
        )
    try:
        return ItemStatus(value.strip())
    except ValueError as error:
        raise LibrarianSkillAcquisitionArtifactError(
            "status must be ACTIVE/NEEDS_REVIEW/DRAFT/ARCHIVED/DEPRECATED/SUPERSEDED"
        ) from error


def _strip_markdown_fences(value: str) -> str:
    stripped = value.strip()
    match = _JSON_BLOCK.search(stripped)
    if match is not None:
        return match.group(1).strip()
    return stripped
