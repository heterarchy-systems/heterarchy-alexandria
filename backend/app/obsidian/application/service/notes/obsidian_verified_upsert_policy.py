"""Pure normalization, identity, and provenance policy for verified upsert."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Final

from app.obsidian.application.graph.relations.obsidian_graph_relation_contracts import (
    ALEXANDRIA_LINKS_END,
    ALEXANDRIA_LINKS_START,
)
from app.obsidian.domain.contracts.obsidian_verified_upsert import (
    ObsidianVerifiedUpsertRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue

_MANAGED_LINKS_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"\n?{re.escape(ALEXANDRIA_LINKS_START)}.*?{re.escape(ALEXANDRIA_LINKS_END)}",
    re.DOTALL,
)
_ACTIVE_STATUSES: Final[frozenset[str]] = frozenset({"active", "current"})


def normalize_verified_upsert_request(
    request: ObsidianVerifiedUpsertRequest,
) -> ObsidianVerifiedUpsertRequest:
    """Normalize request text and validate its compare-and-swap token."""
    identity = request.identity
    normalized_identity = replace(
        identity,
        project=identity.project.strip(),
        report=identity.report.strip(),
        date=identity.date.strip(),
        entity=identity.entity.strip(),
        edition=None if identity.edition is None else identity.edition.strip(),
    )
    expected = request.expected_content_hash
    if expected is not None:
        expected = expected.strip().lower()
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise ObsidianValidationError(
                "expected_content_hash must be a SHA-256 hexadecimal digest"
            )
    tags = tuple(tag.strip() for tag in request.tags if tag.strip())
    return replace(
        request,
        identity=normalized_identity,
        title=request.title.strip(),
        idempotency_key=request.idempotency_key.strip(),
        expected_content_hash=expected,
        tags=tags,
        source=request.source.strip(),
    )


def verified_upsert_request_hash(request: ObsidianVerifiedUpsertRequest) -> str:
    """Hash the complete typed request without accepting opaque metadata."""
    provenance = request.provenance
    payload: JSONObject = {
        "identity": {
            "project": request.identity.project,
            "report": request.identity.report,
            "date": request.identity.date,
            "entity": request.identity.entity,
            "edition": request.identity.edition,
        },
        "title": request.title,
        "body": request.body,
        "alexandria_type": request.alexandria_type.value,
        "expected_content_hash": request.expected_content_hash,
        "tags": list(request.tags),
        "provenance": {
            "source_actor_id": provenance["source_actor_id"],
            "source_actor_type": (
                None
                if provenance["source_actor_type"] is None
                else provenance["source_actor_type"].value
            ),
            "source_run_id": provenance["source_run_id"],
            "external_run_id": provenance["external_run_id"],
            "artifact_refs": list(provenance["artifact_refs"]),
            "evidence_refs": list(provenance["evidence_refs"]),
            "confidence": (
                None
                if provenance["confidence"] is None
                else provenance["confidence"].value
            ),
        },
        "source": request.source,
    }
    return hashlib.sha256(dumps_canonical_json(payload)).hexdigest()


def verified_upsert_frontmatter(
    request: ObsidianVerifiedUpsertRequest,
) -> JSONObject:
    """Create fixed identity/provenance frontmatter owned by the request."""
    provenance = request.provenance
    frontmatter: JSONObject = {
        "report_family": request.identity.report,
        "date": request.identity.date,
        "entity": request.identity.entity,
        "status": "active",
        "source_actor_id": provenance["source_actor_id"],
        "source_run_id": provenance["source_run_id"],
        "external_run_id": provenance["external_run_id"],
        "artifact_refs": list(provenance["artifact_refs"]),
        "evidence_refs": list(provenance["evidence_refs"]),
    }
    if request.alexandria_type is AlexandriaNoteType.CONTEXT:
        frontmatter["scope"] = "PROJECT" if request.identity.project else "GLOBAL"
    if request.identity.edition is not None:
        frontmatter["edition"] = request.identity.edition
    if provenance["source_actor_type"] is not None:
        frontmatter["source_actor_type"] = provenance["source_actor_type"].value
    if provenance["confidence"] is not None:
        frontmatter["confidence"] = provenance["confidence"].value
    return frontmatter


def verified_request_matches_note(
    request: ObsidianVerifiedUpsertRequest,
    note: ObsidianNote,
) -> bool:
    """Compare stable logical/source fields while ignoring managed links."""
    frontmatter = note.frontmatter
    family = frontmatter.get("report_family") or frontmatter.get("report")
    return (
        _same_text(family, request.identity.report)
        and _same_text(frontmatter.get("date"), request.identity.date)
        and _same_text(frontmatter.get("entity"), request.identity.entity)
        and _same_optional_text(frontmatter.get("edition"), request.identity.edition)
        and _same_text(note.project, request.identity.project)
        and is_active_status(note.status)
        and note.title == request.title
        and note.alexandria_type is request.alexandria_type
        and tuple(note.tags) == tuple(request.tags)
        and _same_text(note.source, request.source)
        and _canonical_body(note.body) == _canonical_body(request.body)
        and _same_provenance(frontmatter, request)
    )


def is_active_status(status: object) -> bool:
    """Return whether a lifecycle status is eligible for logical writes."""
    return isinstance(status, str) and status.casefold() in _ACTIVE_STATUSES


def _same_provenance(
    frontmatter: JSONObject,
    request: ObsidianVerifiedUpsertRequest,
) -> bool:
    """Compare only typed provenance fields owned by the request."""
    provenance = request.provenance
    expected: tuple[tuple[str, JSONValue], ...] = (
        ("source_actor_id", provenance["source_actor_id"]),
        ("source_run_id", provenance["source_run_id"]),
        ("external_run_id", provenance["external_run_id"]),
        ("artifact_refs", list(provenance["artifact_refs"])),
        ("evidence_refs", list(provenance["evidence_refs"])),
    )
    for field_name, value in expected:
        if frontmatter.get(field_name) != value:
            return False
    actor_type = (
        None
        if provenance["source_actor_type"] is None
        else provenance["source_actor_type"].value
    )
    confidence = (
        None if provenance["confidence"] is None else provenance["confidence"].value
    )
    return (
        frontmatter.get("source_actor_type") == actor_type
        and frontmatter.get("confidence") == confidence
    )


def _canonical_body(value: str) -> str:
    """Ignore only the managed graph-link block during replay comparison."""
    return _MANAGED_LINKS_PATTERN.sub("", value).strip()


def _same_text(value: object, expected: str) -> bool:
    """Compare a frontmatter scalar to normalized text."""
    return isinstance(value, str) and " ".join(value.casefold().split()) == " ".join(
        expected.casefold().split()
    )


def _same_optional_text(value: object, expected: str | None) -> bool:
    """Compare optional frontmatter text without conflating omission and blank."""
    if expected is None:
        return value is None
    return _same_text(value, expected)
