"""Read-only diagnostics for canonical managed Markdown metadata."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianDataIntegrityPort,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.obsidian.domain.entities.obsidian_raw_source_snapshot import (
    ObsidianRawSourceSnapshot,
)
from app.operations.domain.entities.operational_data_integrity import (
    OperationalDataIntegritySnapshot,
    OperationalDataIntegrityWarning,
)
from app.operations.domain.event_enum.operational_data_integrity_enums import (
    OperationalDataIntegrityStatus,
    OperationalDataIntegrityWarningCode,
)
from app.shared.exceptions.obsidian_exceptions import ObsidianDomainError
from app.shared.infrastructure.critical_task import run_critical_sync
from app.shared.type_validation.frontmatter_metadata_normalization import (
    BooleanField,
    StringCollectionField,
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
            obsidian_service: Obsidian status and bounded raw-source boundary.
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
        if not vault_status.vault_exists or not vault_status.alexandria_root_exists:
            return await run_critical_sync(
                lambda: _build_integrity_snapshot(
                    vault_status=vault_status,
                    source_snapshot=None,
                    checked=False,
                )
            )
        try:
            source_snapshot = await self._obsidian_service.raw_source_snapshot()
        except ObsidianDomainError, OSError, ValueError:
            return await run_critical_sync(
                lambda: _build_integrity_snapshot(
                    vault_status=vault_status,
                    source_snapshot=None,
                    inventory_error=True,
                )
            )
        return await run_critical_sync(
            lambda: _build_integrity_snapshot(
                vault_status=vault_status,
                source_snapshot=source_snapshot,
            )
        )


def _build_integrity_snapshot(
    vault_status: ObsidianVaultStatus,
    source_snapshot: ObsidianRawSourceSnapshot | None,
    *,
    checked: bool = True,
    inventory_error: bool = False,
) -> OperationalDataIntegritySnapshot:
    """Build diagnostics in one worker-local accumulator.

    Args:
        vault_status: Status already collected for operational readiness.
        source_snapshot: Bounded raw source observation, when available.
        checked: Whether source integrity was eligible for inspection.
        inventory_error: Whether source acquisition failed before returning a snapshot.

    Returns:
        Aggregated integrity diagnostics with scan completeness represented.
    """
    findings: dict[
        OperationalDataIntegrityWarningCode,
        _WarningAccumulator,
    ] = {}
    _IntegrityWarningAggregator.record_index_errors(findings, vault_status)
    if inventory_error or (
        source_snapshot is not None
        and (not source_snapshot.complete or source_snapshot.errors)
    ):
        _IntegrityWarningAggregator.record(
            findings, OperationalDataIntegrityWarningCode.INVENTORY_SCAN_ERROR
        )

    scanned_notes = 0
    if source_snapshot is not None:
        for source in source_snapshot.files:
            _scan_markdown(
                markdown=source.raw_text,
                note_path=source.relative_path,
                findings=findings,
            )
            scanned_notes += 1
    return _IntegrityWarningAggregator.snapshot(
        scanned_notes=scanned_notes,
        findings=findings,
        checked=checked,
    )


def _scan_markdown(
    markdown: str,
    note_path: str,
    findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
) -> None:
    """Scan one Markdown document for frontmatter and redaction integrity issues.

    Args:
        markdown: Raw Markdown document text.
        note_path: Vault-relative note path.
        findings: Mutable warning accumulator dictionary.
    """
    fields = _FrontmatterIntegrityScanner.top_level_frontmatter_values(markdown)
    for field_name in sorted(
        metadata_field.value
        for metadata_field in StringCollectionField
        if metadata_field.value in fields
    ):
        raw_field = fields[field_name]
        if _FrontmatterIntegrityScanner.is_yaml_collection(raw_field):
            continue
        if _FrontmatterIntegrityScanner.is_legacy_tuple_collection(raw_field.value):
            _IntegrityWarningAggregator.record(
                findings,
                OperationalDataIntegrityWarningCode.LEGACY_TUPLE_COLLECTION,
                note_path=note_path,
                field_name=field_name,
            )
        elif not raw_field.value and not raw_field.list_items:
            _IntegrityWarningAggregator.record(
                findings,
                OperationalDataIntegrityWarningCode.EMPTY_COLLECTION_SCALAR,
                note_path=note_path,
                field_name=field_name,
            )
        else:
            _IntegrityWarningAggregator.record(
                findings,
                OperationalDataIntegrityWarningCode.INVALID_COLLECTION_TYPE,
                note_path=note_path,
                field_name=field_name,
            )
    for field_name in sorted(
        metadata_field.value
        for metadata_field in BooleanField
        if metadata_field.value in fields
    ):
        if warning_code := _FrontmatterIntegrityScanner.boolean_warning_code(
            fields[field_name].value
        ):
            _IntegrityWarningAggregator.record(
                findings,
                warning_code,
                note_path=note_path,
                field_name=field_name,
            )
    if _UNRECOVERABLE_REDACTED_URL.search(markdown):
        _IntegrityWarningAggregator.record(
            findings,
            OperationalDataIntegrityWarningCode.UNRECOVERABLE_REDACTED_URL,
            note_path=note_path,
        )


class _FrontmatterIntegrityScanner:
    """Inspect raw Markdown frontmatter scalars and collection fields for anomalies."""

    @staticmethod
    def top_level_frontmatter_values(
        markdown: str,
    ) -> dict[str, _RawFrontmatterField]:
        """Extract top-level YAML frontmatter keys, scalar values, and block-list items.

        Args:
            markdown: Raw Markdown document text.

        Returns:
            Mapping from frontmatter field name to its raw scalar and list items.
        """
        lines = markdown.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        values: dict[str, _RawFrontmatterField] = {}
        list_items: dict[str, list[str]] = {}
        active_list_key: str | None = None
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if active_list_key is not None and line.strip().startswith("-"):
                list_items[active_list_key].append(
                    line.strip().removeprefix("-").strip()
                )
                continue
            if line != line.lstrip() or ":" not in line:
                continue
            active_list_key = None
            key, raw_value = line.split(":", maxsplit=1)
            if normalized_key := key.strip():
                value = raw_value.strip()
                values[normalized_key] = _RawFrontmatterField(value=value)
                list_items.pop(normalized_key, None)
                if not value:
                    active_list_key = normalized_key
                    list_items[normalized_key] = []
        for key, field_value in values.items():
            if items := list_items.get(key):
                values[key] = _RawFrontmatterField(
                    value=field_value.value,
                    list_items=tuple(items),
                )
        return values

    @classmethod
    def is_yaml_collection(cls, field: _RawFrontmatterField) -> bool:
        """Check whether a frontmatter field is a valid YAML list of string scalars.

        Args:
            field: Parsed raw frontmatter field.

        Returns:
            True if the field is a valid inline or block YAML string list.
        """
        if not field.value:
            return bool(field.list_items) and all(
                cls._is_string_scalar(item) for item in field.list_items
            )
        if not (field.value.startswith("[") and field.value.endswith("]")):
            return False
        inner = field.value[1:-1].strip()
        if not inner:
            return True
        return all(
            cls._is_string_scalar(item.strip())
            for item in inner.split(",")
            if item.strip()
        )

    @staticmethod
    def is_legacy_tuple_collection(raw_value: str) -> bool:
        """Check whether a scalar value is a serialized Python string tuple.

        Args:
            raw_value: Raw scalar value from frontmatter.

        Returns:
            True if the scalar parses as a tuple of strings.
        """
        candidate = _IntegrityWarningAggregator.unquoted(raw_value)
        if not (candidate.startswith("(") and candidate.endswith(")")):
            return False
        try:
            parsed = ast.literal_eval(candidate)
        except SyntaxError, ValueError:
            return False
        return isinstance(parsed, tuple) and all(
            isinstance(item, str) for item in parsed
        )

    @staticmethod
    def boolean_warning_code(
        raw_value: str,
    ) -> OperationalDataIntegrityWarningCode | None:
        """Classify boolean frontmatter field anomalies.

        Args:
            raw_value: Raw scalar value for a boolean metadata field.

        Returns:
            Warning code if the value is quoted or non-boolean, or None when valid.
        """
        candidate = _IntegrityWarningAggregator.unquoted(raw_value)
        if candidate.casefold() not in {"true", "false"}:
            return OperationalDataIntegrityWarningCode.INVALID_BOOLEAN_VALUE
        if candidate != raw_value:
            return OperationalDataIntegrityWarningCode.STRING_BOOLEAN
        return None

    @staticmethod
    def _is_string_scalar(raw_value: str) -> bool:
        """Check whether a YAML list item represents a string scalar.

        Args:
            raw_value: Raw YAML list item text.

        Returns:
            True if the item is a quoted or unquoted YAML string scalar.
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


class _IntegrityWarningAggregator:
    """Aggregate and freeze operational data-integrity warning accumulators."""

    @staticmethod
    def unquoted(raw_value: str) -> str:
        """Strip matching outer single or double quotes from a YAML scalar string.

        Args:
            raw_value: Raw YAML scalar text.

        Returns:
            Unquoted string content, or the original string if unquoted.
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

    @staticmethod
    def record_index_errors(
        findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
        vault_status: ObsidianVaultStatus,
    ) -> None:
        """Record persisted Obsidian index errors into the warning accumulator.

        Args:
            findings: Mutable warning accumulator dictionary.
            vault_status: Observed Obsidian vault status snapshot.
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

    @staticmethod
    def record(
        findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
        code: OperationalDataIntegrityWarningCode,
        note_path: str | None = None,
        field_name: str | None = None,
    ) -> None:
        """Increment one integrity warning code and record affected note/field names.

        Args:
            findings: Mutable warning accumulator dictionary.
            code: Data-integrity warning code to record.
            note_path: Optional vault-relative note path where the issue occurred.
            field_name: Optional frontmatter field name where the issue occurred.
        """
        finding = findings.setdefault(code, _WarningAccumulator())
        finding.count += 1
        if note_path is not None:
            finding.note_paths.add(note_path)
        if field_name is not None:
            finding.fields.add(field_name)

    @staticmethod
    def snapshot(
        scanned_notes: int,
        findings: dict[OperationalDataIntegrityWarningCode, _WarningAccumulator],
        checked: bool = True,
    ) -> OperationalDataIntegritySnapshot:
        """Freeze accumulated findings into an immutable data-integrity snapshot.

        Args:
            scanned_notes: Total number of Markdown notes scanned.
            findings: Accumulated findings keyed by warning code.
            checked: Whether source files were eligible for scanning.

        Returns:
            Frozen operational data-integrity snapshot entity.
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
