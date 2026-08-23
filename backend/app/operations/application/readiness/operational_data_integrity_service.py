"""Read-only diagnostics for canonical managed Markdown metadata."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianDataIntegrityPort,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.domain.entities.operational_data_integrity import (
    OperationalDataIntegritySnapshot,
    OperationalDataIntegrityWarning,
)
from app.operations.domain.event_enum.operational_data_integrity_enums import (
    OperationalDataIntegrityStatus,
    OperationalDataIntegrityWarningCode,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError
from app.shared.type_validation.frontmatter_metadata_normalization import (
    BOOLEAN_FIELDS,
    STRING_COLLECTION_FIELDS,
)

_UNRECOVERABLE_REDACTED_URL = re.compile(
    r"https?://<REDACTED_LONG_VALUE>",
    re.IGNORECASE,
)
_NUMBER_SCALAR = re.compile(
    r"[-+]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|(?:0|[1-9][0-9]*)[eE][-+]?[0-9]+)"
)


@dataclass(slots=True)
class _WarningAccumulator:
    """Mutable aggregation is local to one bounded diagnostic scan."""

    count: int = 0
    note_paths: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _RawFrontmatterField:
    """Top-level YAML scalar plus any block-list items."""

    value: str
    list_items: tuple[str, ...] = ()


class OperationalDataIntegrityService:
    """Inspect managed Markdown selected by the Obsidian inventory boundary."""

    def __init__(self, obsidian_service: ObsidianDataIntegrityPort) -> None:
        """Create the diagnostic service.

        Args:
            obsidian_service: Obsidian status and managed-inventory boundary.
        """
        self._obsidian_service = obsidian_service

    async def snapshot(
        self,
        vault_status: ObsidianVaultStatus,
    ) -> OperationalDataIntegritySnapshot:
        """Scan canonical managed Markdown and persisted index errors.

        Args:
            vault_status: Status already collected for operational readiness.

        Returns:
            Aggregated, non-mutating data-integrity diagnostics.
        """
        findings: dict[
            OperationalDataIntegrityWarningCode,
            _WarningAccumulator,
        ] = {}
        _record_index_errors(findings, vault_status)
        if not vault_status.vault_exists or not vault_status.alexandria_root_exists:
            return _snapshot(
                scanned_notes=0,
                findings=findings,
                checked=False,
            )
        try:
            managed_paths = await self._obsidian_service.managed_markdown_paths()
        except (ObsidianDomainError, OSError, ValueError):
            _record(
                findings,
                OperationalDataIntegrityWarningCode.INVENTORY_SCAN_ERROR,
            )
            return _snapshot(scanned_notes=0, findings=findings)

        vault_root = Path(vault_status.vault_path).resolve()
        managed_root = (vault_root / vault_status.alexandria_root).resolve()
        scanned_notes = 0
        for relative_path in managed_paths:
            note_path = (vault_root / relative_path).resolve()
            if not note_path.is_relative_to(managed_root):
                _record(
                    findings,
                    OperationalDataIntegrityWarningCode.INVENTORY_SCAN_ERROR,
                    note_path=relative_path,
                )
                continue
            try:
                markdown = note_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                _record(
                    findings,
                    OperationalDataIntegrityWarningCode.INVENTORY_SCAN_ERROR,
                    note_path=relative_path,
                )
                continue
            scanned_notes += 1
            _scan_markdown(
                markdown=markdown,
                note_path=relative_path,
                findings=findings,
            )
        return _snapshot(scanned_notes=scanned_notes, findings=findings)


def _scan_markdown(
    markdown: str,
    note_path: str,
    findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
) -> None:
    """Execute scan markdown.

    Args:
        markdown: Markdown used by this operation.
        note_path: Note path used by this operation.
        findings: Findings used by this operation.
    """
    fields = _top_level_frontmatter_values(markdown)
    for field_name in sorted(STRING_COLLECTION_FIELDS & fields.keys()):
        raw_field = fields[field_name]
        if _is_yaml_collection(raw_field):
            continue
        if _is_legacy_tuple_collection(raw_field.value):
            _record(
                findings,
                OperationalDataIntegrityWarningCode.LEGACY_TUPLE_COLLECTION,
                note_path=note_path,
                field_name=field_name,
            )
        elif not raw_field.value and not raw_field.list_items:
            _record(
                findings,
                OperationalDataIntegrityWarningCode.EMPTY_COLLECTION_SCALAR,
                note_path=note_path,
                field_name=field_name,
            )
        else:
            _record(
                findings,
                OperationalDataIntegrityWarningCode.INVALID_COLLECTION_TYPE,
                note_path=note_path,
                field_name=field_name,
            )
    for field_name in sorted(BOOLEAN_FIELDS & fields.keys()):
        if warning_code := _boolean_warning_code(fields[field_name].value):
            _record(
                findings,
                warning_code,
                note_path=note_path,
                field_name=field_name,
            )
    if _UNRECOVERABLE_REDACTED_URL.search(markdown):
        _record(
            findings,
            OperationalDataIntegrityWarningCode.UNRECOVERABLE_REDACTED_URL,
            note_path=note_path,
        )


def _top_level_frontmatter_values(
    markdown: str,
) -> dict[str, _RawFrontmatterField]:
    """Execute top level frontmatter values.

    Args:
        markdown: Markdown used by this operation.

    Returns:
        dict[str, _RawFrontmatterField] result produced by top level frontmatter values.
    """
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, _RawFrontmatterField] = {}
    active_list_key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if active_list_key is not None and line.strip().startswith("-"):
            field = values[active_list_key]
            values[active_list_key] = _RawFrontmatterField(
                value=field.value,
                list_items=(
                    *field.list_items,
                    line.strip().removeprefix("-").strip(),
                ),
            )
            continue
        if line != line.lstrip() or ":" not in line:
            continue
        active_list_key = None
        key, raw_value = line.split(":", maxsplit=1)
        if normalized_key := key.strip():
            value = raw_value.strip()
            values[normalized_key] = _RawFrontmatterField(value=value)
            if not value:
                active_list_key = normalized_key
    return values


def _is_yaml_collection(field: _RawFrontmatterField) -> bool:
    """Return whether yaml collection.

    Args:
        field: Field used by this operation.

    Returns:
        Whether yaml collection.
    """
    if not field.value:
        return bool(field.list_items) and all(
            _is_string_scalar(item) for item in field.list_items
        )
    if not (field.value.startswith("[") and field.value.endswith("]")):
        return False
    inner = field.value[1:-1].strip()
    if not inner:
        return True
    return all(
        _is_string_scalar(item.strip()) for item in inner.split(",") if item.strip()
    )


def _is_legacy_tuple_collection(raw_value: str) -> bool:
    """Return whether legacy tuple collection.

    Args:
        raw_value: Raw value used by this operation.

    Returns:
        Whether legacy tuple collection.
    """
    candidate = _unquoted(raw_value)
    if not (candidate.startswith("(") and candidate.endswith(")")):
        return False
    try:
        parsed = ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return False
    return isinstance(parsed, tuple) and all(isinstance(item, str) for item in parsed)


def _boolean_warning_code(
    raw_value: str,
) -> OperationalDataIntegrityWarningCode | None:
    """Execute boolean warning code.

    Args:
        raw_value: Raw value used by this operation.

    Returns:
        OperationalDataIntegrityWarningCode | None result produced by boolean warning code.
    """
    candidate = _unquoted(raw_value)
    if candidate.casefold() not in {"true", "false"}:
        return OperationalDataIntegrityWarningCode.INVALID_BOOLEAN_VALUE
    if candidate != raw_value:
        return OperationalDataIntegrityWarningCode.STRING_BOOLEAN
    return None


def _is_string_scalar(raw_value: str) -> bool:
    """Return whether string scalar.

    Args:
        raw_value: Raw value used by this operation.

    Returns:
        Whether string scalar.
    """
    if not raw_value:
        return False
    if (
        len(raw_value) >= 2
        and raw_value[0] in {"'", '"'}
        and raw_value[-1] == raw_value[0]
    ):
        return True
    lowered = raw_value.casefold()
    if lowered in {"true", "false", "null", "~"}:
        return False
    if _NUMBER_SCALAR.fullmatch(raw_value):
        return False
    return not raw_value.startswith(("[", "{"))


def _unquoted(raw_value: str) -> str:
    """Execute unquoted.

    Args:
        raw_value: Raw value used by this operation.

    Returns:
        str result produced by unquoted.
    """
    if (
        len(raw_value) >= 2
        and raw_value[0] in {"'", '"'}
        and raw_value[-1] == raw_value[0]
    ):
        unquoted = raw_value[1:-1]
        if raw_value[0] == "'":
            return unquoted.replace("''", "'")
        return unquoted
    return raw_value


def _record_index_errors(
    findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
    vault_status: ObsidianVaultStatus,
) -> None:
    """Record index errors.

    Args:
        findings: Findings used by this operation.
        vault_status: Vault status used by this operation.
    """
    count = max(vault_status.error_notes, len(vault_status.index_errors))
    if count == 0:
        return
    finding = findings.setdefault(
        OperationalDataIntegrityWarningCode.EXISTING_INDEX_ERRORS,
        _WarningAccumulator(),
    )
    finding.count += count
    finding.note_paths.update(
        error.note_path for error in vault_status.index_errors if error.note_path
    )


def _record(
    findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
    code: OperationalDataIntegrityWarningCode,
    note_path: str | None = None,
    field_name: str | None = None,
) -> None:
    """Execute record.

    Args:
        findings: Findings used by this operation.
        code: Code used by this operation.
        note_path: Note path used by this operation.
        field_name: Field name used by this operation.
    """
    finding = findings.setdefault(code, _WarningAccumulator())
    finding.count += 1
    if note_path is not None:
        finding.note_paths.add(note_path)
    if field_name is not None:
        finding.fields.add(field_name)


def _snapshot(
    scanned_notes: int,
    findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
    checked: bool = True,
) -> OperationalDataIntegritySnapshot:
    """Execute snapshot.

    Args:
        scanned_notes: Scanned notes used by this operation.
        findings: Findings used by this operation.
        checked: Checked used by this operation.

    Returns:
        OperationalDataIntegritySnapshot result produced by snapshot.
    """
    warnings = tuple(
        OperationalDataIntegrityWarning(
            code=code,
            count=finding.count,
            note_paths=tuple(sorted(finding.note_paths)),
            fields=tuple(sorted(finding.fields)),
        )
        for code in OperationalDataIntegrityWarningCode
        if (finding := findings.get(code)) is not None
    )
    return OperationalDataIntegritySnapshot(
        status=(
            OperationalDataIntegrityStatus.DEGRADED
            if warnings
            else (
                OperationalDataIntegrityStatus.HEALTHY
                if checked
                else OperationalDataIntegrityStatus.NOT_CHECKED
            )
        ),
        scanned_notes=scanned_notes,
        warnings=warnings,
    )
