"""Canonical request hashing, path normalization, and report identity policy."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TypedDict

from app.obsidian.application.notes.lifecycle.obsidian_canonical_note_path import (
    canonical_managed_note_path,
)
from app.obsidian.application.notes.report_bundles.report_bundle_enums import (
    ReportBundleIdentityField,
)
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianNoteIndex,
    ObsidianReportBundleRequest,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue


class ReportBundleSourceHashDict(TypedDict):
    """Closed canonical source fields included in a report request hash."""

    title: str
    body: str
    alexandria_type: str
    note_id: str | None
    path: str | None
    tags: list[str]
    status: str
    project: str | None
    source: str | None
    frontmatter: JSONObject
    expected_content_hash: str | None


class ReportBundleOwnerHashDict(TypedDict):
    """Closed canonical graph-owner fields included in a request hash."""

    path: str
    relation: str


class ReportBundleVerifyHashDict(TypedDict):
    """Closed requested verification flags included in a request hash."""

    index_status: bool
    incoming_edges: bool
    duplicates: bool


class ReportBundleRequestHashDict(TypedDict):
    """Closed canonical payload shape used for report request hashing."""

    source: JSONObject
    graph_owners: list[JSONObject]
    reindex: bool
    verify: JSONObject


class ReportBundleIdentityFieldsDict(TypedDict):
    """Normalized business identity fields read from note frontmatter."""

    report_family: str
    report: str
    date: str
    entity: str
    edition: str


type ReportNote = ObsidianNote | ObsidianNoteIndex


def normalize_report_bundle_request(
    request: ObsidianReportBundleRequest,
    alexandria_root: str,
) -> ObsidianReportBundleRequest:
    """Normalize source and owner paths against the configured Alexandria root.

    Args:
        request: Report-bundle request whose paths are normalized.
        alexandria_root: Current configured managed Alexandria root.

    Returns:
        A request with canonical source and owner paths.
    """
    if request.source.relative_path is None:
        raise ObsidianValidationError("report bundle source.path is required")
    source = replace(
        request.source,
        relative_path=canonical_managed_note_path(
            request.source.relative_path,
            alexandria_root=alexandria_root,
        ),
    )
    owners = tuple(
        replace(
            owner,
            path=canonical_managed_note_path(
                owner.path,
                alexandria_root=alexandria_root,
            ),
        )
        for owner in request.graph_owners
    )
    if len({owner.path for owner in owners}) != len(owners):
        raise ObsidianValidationError("graph owner paths must be unique")
    return replace(request, source=source, graph_owners=owners)


def report_bundle_request_hash(request: ObsidianReportBundleRequest) -> str:
    """Build the canonical idempotency hash for one normalized report bundle.

    Args:
        request: Normalized report-bundle request.

    Returns:
        Stable SHA-256 hash of the canonical JSON request payload.
    """
    source_payload = ReportBundleSourceHashDict(
        title=request.source.title,
        body=request.source.body,
        alexandria_type=request.source.alexandria_type.value,
        note_id=request.source.note_id,
        path=request.source.relative_path,
        tags=list(request.source.tags),
        status=request.source.status,
        project=request.source.project,
        source=request.source.source,
        frontmatter=request.source.frontmatter,
        expected_content_hash=request.source.expected_content_hash,
    )
    source_json: JSONObject = dict[str, JSONValue](**source_payload)
    graph_owners: list[JSONObject] = [
        dict[str, JSONValue](
            **ReportBundleOwnerHashDict(
                path=owner.path,
                relation=owner.relation.value,
            )
        )
        for owner in request.graph_owners
    ]
    verify_payload = ReportBundleVerifyHashDict(
        index_status=request.verify.index_status,
        incoming_edges=request.verify.incoming_edges,
        duplicates=request.verify.duplicates,
    )
    verify_json: JSONObject = dict[str, JSONValue](**verify_payload)
    payload = ReportBundleRequestHashDict(
        source=source_json,
        graph_owners=graph_owners,
        reindex=request.reindex,
        verify=verify_json,
    )
    widened_payload: JSONObject = dict[str, JSONValue](**payload)
    return hashlib.sha256(dumps_canonical_json(widened_payload)).hexdigest()


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
    fields = ReportBundleIdentityFieldsDict(
        report_family=_normalized_identity_value(
            left.frontmatter.get(ReportBundleIdentityField.REPORT_FAMILY.value)
        ),
        report=_normalized_identity_value(
            left.frontmatter.get(ReportBundleIdentityField.REPORT.value)
        ),
        date=_normalized_identity_value(
            left.frontmatter.get(ReportBundleIdentityField.DATE.value)
        ),
        entity=_normalized_identity_value(
            left.frontmatter.get(ReportBundleIdentityField.ENTITY.value)
        ),
        edition=_normalized_identity_value(
            left.frontmatter.get(ReportBundleIdentityField.EDITION.value)
        ),
    )
    other_fields = ReportBundleIdentityFieldsDict(
        report_family=_normalized_identity_value(
            right.frontmatter.get(ReportBundleIdentityField.REPORT_FAMILY.value)
        ),
        report=_normalized_identity_value(
            right.frontmatter.get(ReportBundleIdentityField.REPORT.value)
        ),
        date=_normalized_identity_value(
            right.frontmatter.get(ReportBundleIdentityField.DATE.value)
        ),
        entity=_normalized_identity_value(
            right.frontmatter.get(ReportBundleIdentityField.ENTITY.value)
        ),
        edition=_normalized_identity_value(
            right.frontmatter.get(ReportBundleIdentityField.EDITION.value)
        ),
    )
    family = fields["report_family"] or fields["report"]
    other_family = other_fields["report_family"] or other_fields["report"]
    required = (family, fields["date"], fields["entity"])
    if not all(required):
        return False
    return (
        family == other_family
        and fields["date"] == other_fields["date"]
        and fields["entity"] == other_fields["entity"]
        and fields["edition"] == other_fields["edition"]
        and _normalized_identity_value(left.project)
        == _normalized_identity_value(right.project)
    )


# Broad type justified: frontmatter identity values can be any JSON scalar.
def _normalized_identity_value(value: object) -> str:
    """Normalize one declared string identity component.

    Args:
        value: Identity value being processed.

    Returns:
        Case-folded, whitespace-normalized text or an empty string.
    """
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""
