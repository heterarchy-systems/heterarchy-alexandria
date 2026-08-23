"""PostgreSQL full-text helpers for Obsidian vault search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from sqlalchemy import (
    Select,
    bindparam,
    case,
    cast as sql_cast,
    func,
    literal_column,
    select,
    union,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.shared.utils.text_metrics import extract_word_tokens

MAX_FTS_TOKEN_COUNT = 32
MAX_FTS_TOKEN_LENGTH = 64
EXACT_TITLE_FTS_RANK_BOOST = 1.0

type ObsidianFtsRow = tuple[str, str, float]
type ObsidianFtsStatement = Select[ObsidianFtsRow]
type ObsidianFtsParameter = str | int | list[str]


@dataclass(slots=True)
class ObsidianFtsQuery:
    """SQL statement and parameters for one Obsidian PostgreSQL FTS query."""

    statement: ObsidianFtsStatement
    parameters: Mapping[str, ObsidianFtsParameter]

    def __post_init__(self) -> None:
        """Freeze SQL bind parameters after query construction."""
        self.parameters = MappingProxyType(dict(self.parameters))


def build_obsidian_fts_query(
    query_text: str,
    limit: int,
    alexandria_type: AlexandriaNoteType | None = None,
    excluded_alexandria_types: Sequence[AlexandriaNoteType] | None = None,
    excluded_statuses: list[str] | None = None,
    included_statuses: list[str] | None = None,
    excluded_path_prefixes: list[str] | None = None,
    project: str | None = None,
    tags: Sequence[str] | None = None,
) -> ObsidianFtsQuery | None:
    """Build a bound PostgreSQL full-text query from validated search input.

    Args:
        query_text: User search text.
        limit: Maximum number of ranked chunk matches.
        alexandria_type: Optional note type filter.
        excluded_alexandria_types: Note types to exclude.
        excluded_statuses: Note statuses to exclude.
        included_statuses: Note statuses to include.
        excluded_path_prefixes: Vault path prefixes to exclude.
        project: Optional project filter.
        tags: Optional required tags.

    Returns:
        Bound PostgreSQL FTS query, or None when no searchable tokens remain.
    """
    tokens = extract_word_tokens(
        query_text.strip(),
        max_tokens=MAX_FTS_TOKEN_COUNT,
        max_token_length=MAX_FTS_TOKEN_LENGTH,
    )
    if not tokens:
        return None
    normalized = " & ".join(f"{token}:*" for token in tokens)
    config = literal_column("'simple'")
    empty_text = literal_column("''")
    separator = literal_column("' '")
    query = func.to_tsquery(config, bindparam("query"))
    chunk_document = func.to_tsvector(
        config,
        func.coalesce(ObsidianChunkORM.heading_path, empty_text)
        + separator
        + ObsidianChunkORM.text,
    )
    note_document = func.to_tsvector(
        config,
        ObsidianFileORM.title
        + separator
        + ObsidianFileORM.body
        + separator
        + func.coalesce(ObsidianFileORM.project, empty_text)
        + separator
        + ObsidianFileORM.relative_path,
    )
    exact_title_boost = case(
        (
            func.lower(func.trim(ObsidianFileORM.title)) == bindparam("exact_title"),
            EXACT_TITLE_FTS_RANK_BOOST,
        ),
        else_=0.0,
    )
    rank = cast(
        ColumnElement[float],
        (
            func.ts_rank_cd(chunk_document, query)
            + (func.ts_rank_cd(note_document, query) * 0.5)
            + exact_title_boost
        ).label("rank"),
    )
    chunk_candidates = select(ObsidianChunkORM.id.label("chunk_id")).where(
        chunk_document.op("@@")(query)
    )
    note_candidates = (
        select(ObsidianChunkORM.id.label("chunk_id"))
        .select_from(ObsidianFileORM)
        .join(ObsidianChunkORM, ObsidianChunkORM.note_id == ObsidianFileORM.note_id)
        .where(note_document.op("@@")(query))
    )
    candidates = union(chunk_candidates, note_candidates).subquery(
        "obsidian_fts_candidates"
    )
    statement = (
        select(ObsidianChunkORM.id, ObsidianChunkORM.note_id, rank)
        .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
        .join(candidates, candidates.c.chunk_id == ObsidianChunkORM.id)
        .where(ObsidianFileORM.index_status == bindparam("indexed_status"))
    )
    parameters: dict[str, ObsidianFtsParameter] = {
        "query": normalized,
        "exact_title": query_text.strip().lower(),
        "limit": limit,
        "indexed_status": "indexed",
    }
    if alexandria_type is not None:
        statement = statement.where(
            ObsidianFileORM.alexandria_type == bindparam("alexandria_type")
        )
        parameters["alexandria_type"] = alexandria_type.value
    if excluded_alexandria_types:
        statement = statement.where(
            ObsidianFileORM.alexandria_type.not_in(
                bindparam("excluded_alexandria_types", expanding=True)
            )
        )
        parameters["excluded_alexandria_types"] = [
            note_type.value for note_type in excluded_alexandria_types
        ]
    if excluded_statuses:
        statement = statement.where(
            func.lower(ObsidianFileORM.status).not_in(
                bindparam("excluded_statuses", expanding=True)
            )
        )
        parameters["excluded_statuses"] = [
            status.strip().lower() for status in excluded_statuses
        ]
    if included_statuses:
        normalized_status = func.coalesce(
            func.nullif(func.lower(func.trim(ObsidianFileORM.status)), ""),
            "active",
        )
        statement = statement.where(
            normalized_status.in_(bindparam("included_statuses", expanding=True))
        )
        parameters["included_statuses"] = [
            status.strip().lower() for status in included_statuses
        ]
    if excluded_path_prefixes:
        for index, prefix in enumerate(excluded_path_prefixes):
            parameter_name = f"excluded_path_prefix_{index}"
            statement = statement.where(
                ~ObsidianFileORM.relative_path.like(
                    bindparam(parameter_name),
                    escape="\\",
                )
            )
            parameters[parameter_name] = f"{_escape_like_pattern(prefix)}%"
    if project is not None:
        statement = statement.where(ObsidianFileORM.project == bindparam("project"))
        parameters["project"] = project
    if tags:
        tags_jsonb = sql_cast(ObsidianFileORM.tags, JSONB)
        for index, tag in enumerate(tags):
            parameter_name = f"required_tag_{index}"
            statement = statement.where(
                tags_jsonb.contains(bindparam(parameter_name, type_=JSONB))
            )
            parameters[parameter_name] = [tag]
    statement = statement.order_by(rank.desc()).limit(bindparam("limit"))
    return ObsidianFtsQuery(
        statement=cast(ObsidianFtsStatement, statement),
        parameters=parameters,
    )


def _escape_like_pattern(value: str) -> str:
    """Execute escape like pattern.

    Args:
        value: Value being processed.

    Returns:
        str result produced by escape like pattern.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
