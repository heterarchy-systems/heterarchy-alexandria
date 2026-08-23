"""Obsidian legacy metadata repair support."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Sequence
from pathlib import Path

from app.obsidian.domain.entities.obsidian_legacy_metadata_repair import (
    LegacyMetadataValue,
    ObsidianLegacyMetadataRepairCandidate,
    ObsidianLegacyMetadataRepairFinding,
    ObsidianLegacyMetadataRepairPlan,
    ObsidianLegacyMetadataRepairResult,
)
from app.obsidian.infrastructure.markdown.atomic_markdown_write import (
    atomic_write_markdown,
)
from app.obsidian.infrastructure.markdown.paths import (
    resolve_note_path,
    validate_discovered_note_path,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianValidationError
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.type_validation.frontmatter_metadata_normalization import (
    BOOLEAN_FIELDS,
    STRING_COLLECTION_FIELDS,
    normalize_boolean_metadata,
)
from app.shared.types.extra_types import JSONObject, JSONValue


def _empty_plan() -> ObsidianLegacyMetadataRepairPlan:
    """Execute empty plan.

    Returns:
        ObsidianLegacyMetadataRepairPlan result produced by empty plan.
    """
    candidates: tuple[ObsidianLegacyMetadataRepairCandidate, ...] = ()
    return ObsidianLegacyMetadataRepairPlan(
        plan_hash=_plan_hash(
            candidates=candidates,
            scanned_documents=0,
            unrecoverable_redacted_urls=0,
        ),
        dry_run=True,
        backup_required=True,
        scanned_documents=0,
        affected_documents=0,
        repairable_fields=0,
        manual_review_fields=0,
        unrecoverable_redacted_urls=0,
        candidates=candidates,
    )


def _scan_frontmatter(
    text: str,
) -> tuple[ObsidianLegacyMetadataRepairFinding, ...]:
    """Execute scan frontmatter.

    Args:
        text: Text used by this operation.

    Returns:
        tuple[ObsidianLegacyMetadataRepairFinding, ...] result produced by scan frontmatter.
    """
    lines, end_index = _frontmatter_lines(text)
    if end_index is None:
        return ()
    findings: list[ObsidianLegacyMetadataRepairFinding] = []
    for line_index, line in enumerate(lines[1:end_index], start=1):
        raw_line = line.rstrip("\r\n")
        if raw_line != raw_line.lstrip() or ":" not in raw_line:
            continue
        field_name, raw_value = raw_line.split(":", maxsplit=1)
        field_name = field_name.strip()
        current_value = raw_value.strip()
        scalar_value = _quoted_scalar(current_value)
        if field_name in STRING_COLLECTION_FIELDS:
            if not current_value:
                if not _has_block_list_items(
                    lines=lines,
                    start_index=line_index + 1,
                    end_index=end_index,
                ):
                    findings.append(
                        ObsidianLegacyMetadataRepairFinding(
                            field_name=field_name,
                            current_value=current_value,
                            proposed_value=(),
                            reason="empty_collection_scalar",
                            is_repairable=True,
                        )
                    )
                continue
            collection_value = (
                scalar_value
                if scalar_value is not None
                else _plain_legacy_collection_scalar(current_value)
            )
            if collection_value is not None:
                finding = _collection_finding(
                    field_name=field_name,
                    current_value=current_value,
                    scalar_value=collection_value,
                )
                if finding is not None:
                    findings.append(finding)
        elif field_name in BOOLEAN_FIELDS:
            boolean_value = scalar_value if scalar_value is not None else current_value
            try:
                normalized = normalize_boolean_metadata(boolean_value)
            except ValueError:
                findings.append(
                    ObsidianLegacyMetadataRepairFinding(
                        field_name=field_name,
                        current_value=current_value,
                        proposed_value=None,
                        reason="manual_review:invalid_boolean",
                        is_repairable=False,
                    )
                )
            else:
                if scalar_value is not None:
                    findings.append(
                        ObsidianLegacyMetadataRepairFinding(
                            field_name=field_name,
                            current_value=current_value,
                            proposed_value=normalized,
                            reason="string_boolean",
                            is_repairable=True,
                        )
                    )
    return tuple(findings)


def _collection_finding(
    field_name: str,
    current_value: str,
    scalar_value: str,
) -> ObsidianLegacyMetadataRepairFinding | None:
    """Execute collection finding.

    Args:
        field_name: Field name used by this operation.
        current_value: Current value used by this operation.
        scalar_value: Scalar value used by this operation.

    Returns:
        ObsidianLegacyMetadataRepairFinding | None result produced by collection finding.
    """
    stripped = scalar_value.strip()
    if not (
        (stripped.startswith("(") and stripped.endswith(")"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return None
    try:
        normalized = _normalize_legacy_string_collection(stripped)
    except ValueError:
        return ObsidianLegacyMetadataRepairFinding(
            field_name=field_name,
            current_value=current_value,
            proposed_value=None,
            reason="manual_review:invalid_collection_repr",
            is_repairable=False,
        )
    return ObsidianLegacyMetadataRepairFinding(
        field_name=field_name,
        current_value=current_value,
        proposed_value=normalized,
        reason="legacy_collection_repr",
        is_repairable=True,
    )


def _normalize_legacy_string_collection(value: str) -> tuple[str, ...]:
    """Normalize legacy string collection.

    Args:
        value: Value being processed.

    Returns:
        Normalized legacy string collection.
    """
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise ValueError("invalid legacy collection representation") from exc
    if not isinstance(parsed, list | tuple):
        raise ValueError("legacy collection must be a list or tuple")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            raise ValueError("legacy collection items must be strings")
        text = item.strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return tuple(normalized)


def _quoted_scalar(value: str) -> str | None:
    """Execute quoted scalar.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by quoted scalar.
    """
    if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"'}:
        return None
    if value[0] == "'":
        return value[1:-1].replace("''", "'")
    return value[1:-1]


def _plain_legacy_collection_scalar(value: str) -> str | None:
    """Execute plain legacy collection scalar.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by plain legacy collection scalar.
    """
    stripped = value.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped
    return None


def _has_block_list_items(
    lines: Sequence[str],
    start_index: int,
    end_index: int,
) -> bool:
    """Return whether block list items.

    Args:
        lines: Lines used by this operation.
        start_index: Start index used by this operation.
        end_index: End index used by this operation.

    Returns:
        Whether block list items.
    """
    for line in lines[start_index:end_index]:
        if line == line.lstrip() and line.strip():
            return False
        if line.strip().startswith("-"):
            return True
    return False


def _apply_findings(
    text: str,
    findings: tuple[ObsidianLegacyMetadataRepairFinding, ...],
) -> str:
    """Apply findings.

    Args:
        text: Text used by this operation.
        findings: Findings used by this operation.

    Returns:
        str result produced by apply findings.
    """
    lines, end_index = _frontmatter_lines(text)
    if end_index is None:
        raise ValueError("FRONTMATTER_PARSE_ERROR: frontmatter is required")
    finding_by_field = {item.field_name: item for item in findings}
    output: list[str] = [lines[0]]
    replaced_fields: set[str] = set()
    for line in lines[1:end_index]:
        raw_line = line.rstrip("\r\n")
        field_name = (
            raw_line.split(":", maxsplit=1)[0].strip()
            if raw_line == raw_line.lstrip() and ":" in raw_line
            else ""
        )
        finding = finding_by_field.get(field_name)
        if finding is None:
            output.append(line)
            continue
        line_ending = line[len(raw_line) :] or "\n"
        output.extend(
            _render_replacement(
                field_name=field_name,
                value=finding.proposed_value,
                line_ending=line_ending,
            )
        )
        replaced_fields.add(field_name)
    if replaced_fields != set(finding_by_field):
        raise ValueError("legacy metadata repair target changed")
    output.extend(lines[end_index:])
    return "".join(output)


def _render_replacement(
    field_name: str,
    value: LegacyMetadataValue,
    line_ending: str,
) -> list[str]:
    """Render replacement.

    Args:
        field_name: Field name used by this operation.
        value: Value being processed.
        line_ending: Line ending used by this operation.

    Returns:
        Rendered replacement.
    """
    if isinstance(value, tuple):
        if not value:
            return [f"{field_name}: []{line_ending}"]
        return [
            f"{field_name}:{line_ending}",
            *[f"  - {_yaml_string(item)}{line_ending}" for item in value],
        ]
    if isinstance(value, bool):
        return [f"{field_name}: {'true' if value else 'false'}{line_ending}"]
    raise ValueError("legacy metadata repair has no proposed value")


def _yaml_string(value: str) -> str:
    """Execute yaml string.

    Args:
        value: Value being processed.

    Returns:
        str result produced by yaml string.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _frontmatter_lines(text: str) -> tuple[list[str], int | None]:
    """Execute frontmatter lines.

    Args:
        text: Text used by this operation.

    Returns:
        tuple[list[str], int | None] result produced by frontmatter lines.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n").strip() != "---":
        return lines, None
    end_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n").strip() == "---"
        ),
        None,
    )
    return lines, end_index


def _plan_hash(
    candidates: tuple[ObsidianLegacyMetadataRepairCandidate, ...],
    scanned_documents: int,
    unrecoverable_redacted_urls: int,
) -> str:
    """Execute plan hash.

    Args:
        candidates: Candidates used by this operation.
        scanned_documents: Scanned documents used by this operation.
        unrecoverable_redacted_urls: Unrecoverable redacted urls used by this operation.

    Returns:
        str result produced by plan hash.
    """
    payload: JSONObject = {
        "scanned_documents": scanned_documents,
        "unrecoverable_redacted_urls": unrecoverable_redacted_urls,
        "candidates": [
            {
                "note_path": candidate.note_path,
                "original_sha256": candidate.original_sha256,
                "findings": [
                    {
                        "field_name": finding.field_name,
                        "current_value": finding.current_value,
                        "proposed_value": _json_metadata_value(finding.proposed_value),
                        "reason": finding.reason,
                        "is_repairable": finding.is_repairable,
                    }
                    for finding in candidate.findings
                ],
            }
            for candidate in candidates
        ],
    }
    encoded = dumps_canonical_json(payload)
    return _sha256(encoded)


def _json_metadata_value(value: LegacyMetadataValue) -> JSONValue:
    """Normalize one legacy metadata value for deterministic JSON hashing.

    Args:
        value: Value being processed.

    Returns:
        JSONValue result produced by json metadata value.
    """

    if isinstance(value, tuple):
        return list(value)
    return value


def _preflight_and_backup(
    vault_path: Path,
    alexandria_root: str,
    operation_root: str,
    candidates: Sequence[ObsidianLegacyMetadataRepairCandidate],
) -> dict[str, tuple[Path, bytes]]:
    """Execute preflight and backup.

    Args:
        vault_path: Vault path used by this operation.
        alexandria_root: Alexandria root used by this operation.
        operation_root: Operation root used by this operation.
        candidates: Candidates used by this operation.

    Returns:
        dict[str, tuple[Path, bytes]] result produced by preflight and backup.
    """
    originals: dict[str, tuple[Path, bytes]] = {}
    for candidate in candidates:
        path = validate_discovered_note_path(
            vault_path,
            alexandria_root,
            resolve_note_path(vault_path, candidate.note_path),
        )
        raw = path.read_bytes()
        if _sha256(raw) != candidate.original_sha256:
            raise ObsidianValidationError(
                f"legacy metadata repair source changed: {candidate.note_path}"
            )
        backup = resolve_note_path(
            vault_path,
            f"{operation_root}/{candidate.note_path}.original",
        )
        if backup.exists():
            raise ObsidianValidationError("legacy metadata repair backup exists")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
        if backup.read_bytes() != raw:
            raise ObsidianValidationError(
                "legacy metadata repair backup verification failed"
            )
        originals[candidate.note_path] = (path, raw)
    return originals


def _rollback_successful_repairs(
    originals: dict[str, tuple[Path, bytes]],
    results: Sequence[ObsidianLegacyMetadataRepairResult],
) -> None:
    """Restore originals if the required post-apply reindex fails.

    Args:
        originals: Originals used by this operation.
        results: Results used by this operation.
    """
    for result in results:
        if not result.success:
            continue
        path, raw = originals[result.note_path]
        atomic_write_markdown(path, raw.decode("utf-8"))


def _sha256(value: bytes) -> str:
    """Execute sha256.

    Args:
        value: Value being processed.

    Returns:
        str result produced by sha256.
    """
    return hashlib.sha256(value).hexdigest()
