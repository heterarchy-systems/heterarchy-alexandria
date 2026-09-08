"""Canonical request hashing and duplicate identity policy for report bundles."""

from __future__ import annotations

import hashlib

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianNoteIndex,
    ObsidianReportBundleRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue


def report_bundle_request_hash(request: ObsidianReportBundleRequest) -> str:
    """Build the canonical idempotency hash for one report bundle.

    Args:
        request: Normalized report-bundle request.

    Returns:
        Stable SHA-256 hash of the canonical JSON request payload.
    """
    tags: list[JSONValue] = list(request.source.tags)
    source_payload: JSONObject = {
        "title": request.source.title,
        "body": request.source.body,
        "alexandria_type": request.source.alexandria_type.value,
        "note_id": request.source.note_id,
        "path": request.source.relative_path,
        "tags": tags,
        "status": request.source.status,
        "project": request.source.project,
        "source": request.source.source,
        "frontmatter": request.source.frontmatter,
        "expected_content_hash": request.source.expected_content_hash,
    }
    graph_owners: list[JSONValue] = [
        {"path": owner.path, "relation": owner.relation.value}
        for owner in request.graph_owners
    ]
    verify_payload: JSONObject = {
        "index_status": request.verify.index_status,
        "incoming_edges": request.verify.incoming_edges,
        "duplicates": request.verify.duplicates,
    }
    payload: JSONObject = {
        "source": source_payload,
        "graph_owners": graph_owners,
        "reindex": request.reindex,
        "verify": verify_payload,
    }
    return hashlib.sha256(dumps_canonical_json(payload)).hexdigest()


type ReportNote = ObsidianNote | ObsidianNoteIndex


def same_report_content(left: ReportNote, right: ReportNote) -> bool:
    """Compare canonical content hashes for two report notes.

    Args:
        left: First canonical report note.
        right: Second canonical report note.

    Returns:
        Whether both notes declare the same non-empty content hash.
    """
    left_hash = left.frontmatter.get("content_hash")
    right_hash = right.frontmatter.get("content_hash")
    return isinstance(left_hash, str) and bool(left_hash) and left_hash == right_hash


def same_report_identity(left: ReportNote, right: ReportNote) -> bool:
    """Compare the declared business identity of two report notes.

    Args:
        left: First canonical report note.
        right: Second canonical report note.

    Returns:
        Whether report family, date, entity, edition, and project agree.
    """
    fields = ("report_family", "report", "date", "entity", "edition")
    left_values = {
        field: _normalized_identity_value(left.frontmatter.get(field))
        for field in fields
    }
    right_values = {
        field: _normalized_identity_value(right.frontmatter.get(field))
        for field in fields
    }
    left_family = left_values["report_family"] or left_values["report"]
    right_family = right_values["report_family"] or right_values["report"]
    required = (left_family, left_values["date"], left_values["entity"])
    if not all(required):
        return False
    return (
        left_family == right_family
        and left_values["date"] == right_values["date"]
        and left_values["entity"] == right_values["entity"]
        and left_values["edition"] == right_values["edition"]
        and _normalized_identity_value(left.project)
        == _normalized_identity_value(right.project)
    )


# Broad type justified: frontmatter identity values can be any JSON scalar.
def _normalized_identity_value(value: object) -> str:
    """Execute normalized identity value.

    Args:
        value: Value being processed.

    Returns:
        str result produced by normalized identity value.
    """
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""
