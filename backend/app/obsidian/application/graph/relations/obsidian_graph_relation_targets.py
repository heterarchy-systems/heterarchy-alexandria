"""Dynamic frontmatter target parsing for Obsidian graph relations."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from app.obsidian.domain.event_enum.obsidian_enums import ObsidianRelationType
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONObject, JSONValue


class _RelationTarget:
    def __init__(
        self,
        path: str | None,
        note_id: str | None,
        relation: ObsidianRelationType | None,
    ) -> None:
        """Initialize _RelationTarget state and dependencies.

        Args:
            path: Path used by this operation.
            note_id: Identifier for note.
            relation: Relation used by this operation.
        """
        self.path = path
        self.note_id = note_id
        self.relation = relation


def _relation_targets(
    value: JSONValue | None,
    field_name: str | None = None,
) -> Iterable[_RelationTarget]:
    """Execute relation targets.

    Args:
        value: Value being processed.
        field_name: Field name used by this operation.

    Returns:
        Iterable[_RelationTarget] result produced by relation targets.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        sequence = _target_sequence_from_string(value)
        if sequence is not None:
            return tuple(
                target
                for item in sequence
                for target in _relation_targets(item, field_name=field_name)
            )
        parsed = _target_mapping_from_string(value)
        if parsed is not None:
            return (_target_from_mapping(parsed, field_name=field_name),)
        return (_RelationTarget(path=value, note_id=None, relation=None),)
    if isinstance(value, Mapping):
        return (_target_from_mapping(value, field_name=field_name),)
    if isinstance(value, Sequence):
        targets: list[_RelationTarget] = []
        for item in value:
            if isinstance(item, str):
                parsed = _target_mapping_from_string(item)
                if parsed is not None:
                    targets.append(_target_from_mapping(parsed, field_name=field_name))
                else:
                    targets.append(
                        _RelationTarget(path=item, note_id=None, relation=None)
                    )
            elif isinstance(item, Mapping):
                targets.append(
                    _target_from_mapping(cast(JSONObject, item), field_name=field_name)
                )
        return targets
    return ()


def _target_mapping_from_string(value: str) -> Mapping[str, JSONValue] | None:
    """Execute target mapping from string.

    Args:
        value: Value being processed.

    Returns:
        Mapping[str, JSONValue] | None result produced by target mapping from string.
    """
    if not value.lstrip().startswith("{"):
        return None
    parsed = _structured_value(value)
    if not isinstance(parsed, Mapping):
        return None
    return cast(JSONObject, parsed)


def _target_sequence_from_string(value: str) -> Sequence[JSONValue] | None:
    """Execute target sequence from string.

    Args:
        value: Value being processed.

    Returns:
        Sequence[JSONValue] | None result produced by target sequence from string.
    """
    if not value.lstrip().startswith("["):
        return None
    parsed = _structured_value(value)
    if not isinstance(parsed, Sequence) or isinstance(parsed, str):
        return None
    return cast(Sequence[JSONValue], parsed)


def _structured_value(value: str) -> JSONValue | None:
    """Execute structured value.

    Args:
        value: Value being processed.

    Returns:
        JSONValue | None result produced by structured value.
    """
    try:
        return loads_json(value)
    except ValueError:
        try:
            return cast(JSONValue, ast.literal_eval(value))
        except (SyntaxError, ValueError):
            return None


def _target_from_mapping(
    value: Mapping[str, JSONValue],
    field_name: str | None,
) -> _RelationTarget:
    """Execute target from mapping.

    Args:
        value: Value being processed.
        field_name: Field name used by this operation.

    Returns:
        _RelationTarget result produced by target from mapping.
    """
    path = (
        _string_field(value, "path")
        or _string_field(value, "target_path")
        or (
            _string_field(value, "detail_path") if field_name == "source_refs" else None
        )
    )
    source_id = (
        _string_field(value, "source_id") if field_name == "source_refs" else None
    )
    note_id = (
        source_id
        or _string_field(value, "target_note_id")
        or _string_field(value, "id")
    )
    relation_value = _string_field(value, "relation")
    relation = _relation_or_none(relation_value)
    return _RelationTarget(path=path, note_id=note_id, relation=relation)


def _string_field(value: Mapping[str, JSONValue], key: str) -> str | None:
    """Execute string field.

    Args:
        value: Value being processed.
        key: Key used by this operation.

    Returns:
        str | None result produced by string field.
    """
    raw = value.get(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _relation_or_none(value: str | None) -> ObsidianRelationType | None:
    """Execute relation or none.

    Args:
        value: Value being processed.

    Returns:
        ObsidianRelationType | None result produced by relation or none.
    """
    if value is None:
        return None
    try:
        return ObsidianRelationType(value)
    except ValueError:
        return None


def source_refs_from_json(value: JSONValue | None) -> list[JSONObject]:
    """Return relation objects from a dynamic JSON value.

    Args:
        value: Dynamic boundary value expected to contain source refs.

    Returns:
        JSON object refs with path/id when present.
    """
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
