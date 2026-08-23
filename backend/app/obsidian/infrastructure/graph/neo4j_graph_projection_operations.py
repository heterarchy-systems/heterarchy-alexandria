"""Neo4j graph projection operations."""

from __future__ import annotations

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphContextEvidence,
    ObsidianGraphProjection,
    ObsidianGraphProjectionEdge,
    ObsidianGraphProjectionIssueCount,
    ObsidianGraphProjectionNode,
    ObsidianGraphProjectionState,
    ObsidianGraphRelatedNote,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianEdgeSourceKind,
    ObsidianRelationType,
)
from app.obsidian.domain.event_enum.obsidian_graph_enums import (
    ObsidianGraphContextSignalType,
    ObsidianGraphDirection,
    ObsidianGraphProjectionIssueCode,
)
from app.obsidian.infrastructure.graph.neo4j_graph_projection_contracts import (
    PROJECTION_NAME,
    Neo4jProjectionActivationParameters,
    Neo4jProjectionEdgeParameters,
    Neo4jProjectionNodeParameters,
    Neo4jProjectionRawRow,
    Neo4jProjectionRunParameters,
    Neo4jProjectionTransaction,
)
from app.obsidian.infrastructure.graph.neo4j_graph_projection_queries import (
    ACTIVATE_PROJECTION_METADATA,
    CREATE_NOTE_KEY_CONSTRAINT,
    CREATE_PROJECTION_NAME_CONSTRAINT,
    DELETE_PROJECTION_RUN_NODES,
    READ_CONTEXT_EVIDENCE,
    READ_EDGES,
    READ_NODES,
    READ_PROJECTION_METADATA,
    READ_RELATED_NOTES,
    UPSERT_EDGES,
    UPSERT_NODES,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json, loads_json


async def _ensure_constraints(transaction: Neo4jProjectionTransaction) -> None:
    """Ensure constraints.

    Args:
        transaction: Transaction boundary used by this operation.
    """
    await (await transaction.run(CREATE_NOTE_KEY_CONSTRAINT)).consume()
    await (await transaction.run(CREATE_PROJECTION_NAME_CONSTRAINT)).consume()


async def _upsert_projection(
    transaction: Neo4jProjectionTransaction,
    projection: ObsidianGraphProjection,
    run_id: str,
    projection_version: int,
) -> None:
    """Execute upsert projection.

    Args:
        transaction: Transaction boundary used by this operation.
        projection: Projection used by this operation.
        run_id: Identifier for run.
        projection_version: Projection version used by this operation.
    """
    run_parameters = _run_parameters(run_id, projection_version)
    await (
        await transaction.run(
            UPSERT_NODES,
            nodes=[_node_parameters(node, run_id=run_id) for node in projection.nodes],
            **run_parameters,
        )
    ).consume()
    await (
        await transaction.run(
            UPSERT_EDGES,
            edges=[_edge_parameters(edge, run_id=run_id) for edge in projection.edges],
            **run_parameters,
        )
    ).consume()


async def _delete_projection_run(
    transaction: Neo4jProjectionTransaction, run_id: str
) -> None:
    """Delete projection run.

    Args:
        transaction: Transaction boundary used by this operation.
        run_id: Identifier for run.
    """
    await (
        await transaction.run(
            DELETE_PROJECTION_RUN_NODES,
            projection_name=PROJECTION_NAME,
            run_id=run_id,
        )
    ).consume()


async def _activate_projection(
    transaction: Neo4jProjectionTransaction,
    run_id: str,
    projection_version: int,
    issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...],
) -> None:
    """Execute activate projection.

    Args:
        transaction: Transaction boundary used by this operation.
        run_id: Identifier for run.
        projection_version: Projection version used by this operation.
        issue_counts: Issue counts used by this operation.
    """
    parameters = _activation_parameters(run_id, projection_version, issue_counts)
    await (await transaction.run(ACTIVATE_PROJECTION_METADATA, **parameters)).consume()


async def _read_projection_state(
    transaction: Neo4jProjectionTransaction,
) -> ObsidianGraphProjectionState:
    """Read projection state.

    Args:
        transaction: Transaction boundary used by this operation.

    Returns:
        Loaded projection state.
    """
    metadata_result = await transaction.run(
        READ_PROJECTION_METADATA,
        projection_name=PROJECTION_NAME,
    )
    metadata_rows = await metadata_result.data()
    await metadata_result.consume()
    metadata: Neo4jProjectionRawRow = metadata_rows[0] if metadata_rows else {}
    run_id = _optional_text(metadata, "run_id")
    version = metadata.get("projection_version")
    if run_id is None:
        return ObsidianGraphProjectionState(initialized=False)
    if not isinstance(version, int):
        raise TypeError("Neo4j projection metadata requires integer version")
    issue_total = metadata.get("issue_total")
    if issue_total is not None and not isinstance(issue_total, int):
        raise TypeError("Neo4j projection metadata issue_total must be integer")
    issue_counts = _issue_counts_from_json(
        _optional_text(metadata, "issue_counts_json")
    )
    node_result = await transaction.run(
        READ_NODES,
        projection_name=PROJECTION_NAME,
        run_id=run_id,
    )
    node_rows = await node_result.data()
    await node_result.consume()
    edge_result = await transaction.run(
        READ_EDGES,
        projection_name=PROJECTION_NAME,
        run_id=run_id,
    )
    edge_rows = await edge_result.data()
    await edge_result.consume()
    return ObsidianGraphProjectionState(
        initialized=True,
        run_id=run_id,
        projection_version=version,
        issue_total=issue_total or 0,
        issue_counts=issue_counts,
        projection=ObsidianGraphProjection(
            nodes=tuple(_node_from_row(row) for row in node_rows),
            edges=tuple(_edge_from_row(row) for row in edge_rows),
        ),
    )


async def _read_related_notes(
    transaction: Neo4jProjectionTransaction,
    note_id: str,
    limit: int,
) -> tuple[ObsidianGraphRelatedNote, ...]:
    """Read related notes.

    Args:
        transaction: Transaction boundary used by this operation.
        note_id: Identifier for note.
        limit: Maximum number of items to process or return.

    Returns:
        Loaded related notes.
    """
    query_result = await transaction.run(
        READ_RELATED_NOTES,
        projection_name=PROJECTION_NAME,
        note_id=note_id,
        limit=limit,
    )
    rows = await query_result.data()
    await query_result.consume()
    return tuple(_related_note_from_row(row) for row in rows)


async def _read_context_evidence(
    transaction: Neo4jProjectionTransaction,
    note_ids: tuple[str, ...],
) -> tuple[ObsidianGraphContextEvidence, ...]:
    """Read context evidence.

    Args:
        transaction: Transaction boundary used by this operation.
        note_ids: Identifiers for note.

    Returns:
        Loaded context evidence.
    """
    query_result = await transaction.run(
        READ_CONTEXT_EVIDENCE,
        projection_name=PROJECTION_NAME,
        note_ids=list(note_ids),
    )
    rows = await query_result.data()
    await query_result.consume()
    return tuple(_context_evidence_from_row(row) for row in rows)


def _run_parameters(
    run_id: str, projection_version: int
) -> Neo4jProjectionRunParameters:
    """Run parameters.

    Args:
        run_id: Identifier for run.
        projection_version: Projection version used by this operation.

    Returns:
        Neo4jProjectionRunParameters result produced by run parameters.
    """
    return {
        "projection_name": PROJECTION_NAME,
        "projection_version": projection_version,
        "run_id": run_id,
    }


def _activation_parameters(
    run_id: str,
    projection_version: int,
    issue_counts: tuple[ObsidianGraphProjectionIssueCount, ...],
) -> Neo4jProjectionActivationParameters:
    """Execute activation parameters.

    Args:
        run_id: Identifier for run.
        projection_version: Projection version used by this operation.
        issue_counts: Issue counts used by this operation.

    Returns:
        Neo4jProjectionActivationParameters result produced by activation parameters.
    """
    return {
        **_run_parameters(run_id, projection_version),
        "issue_total": sum(item.count for item in issue_counts),
        "issue_counts_json": dumps_canonical_json(
            {item.code.value: item.count for item in issue_counts}
        ).decode("utf-8"),
    }


def _issue_counts_from_json(
    value: str | None,
) -> tuple[ObsidianGraphProjectionIssueCount, ...]:
    """Execute issue counts from json.

    Args:
        value: Value being processed.

    Returns:
        tuple[ObsidianGraphProjectionIssueCount, ...] result produced by issue counts from json.
    """
    if value is None:
        return ()
    try:
        payload = loads_json(value)
    except ValueError as exc:
        raise TypeError("Neo4j projection issue summary must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("Neo4j projection issue summary must be an object")
    counts: list[ObsidianGraphProjectionIssueCount] = []
    for raw_code, raw_count in sorted(payload.items()):
        if not isinstance(raw_code, str) or not isinstance(raw_count, int):
            raise TypeError("Neo4j projection issue summary entries are invalid")
        counts.append(
            ObsidianGraphProjectionIssueCount(
                code=ObsidianGraphProjectionIssueCode(raw_code),
                count=raw_count,
            )
        )
    return tuple(counts)


def _node_parameters(
    node: ObsidianGraphProjectionNode,
    run_id: str,
) -> Neo4jProjectionNodeParameters:
    """Execute node parameters.

    Args:
        node: Node used by this operation.
        run_id: Identifier for run.

    Returns:
        Neo4jProjectionNodeParameters result produced by node parameters.
    """
    return {
        "projection_key": f"{run_id}:note:{node.note_id}",
        "note_id": node.note_id,
        "relative_path": node.relative_path,
        "alexandria_type": node.alexandria_type.value,
        "title": node.title,
        "status": node.status,
        "project": node.project,
    }


def _edge_parameters(
    edge: ObsidianGraphProjectionEdge,
    run_id: str,
) -> Neo4jProjectionEdgeParameters:
    """Execute edge parameters.

    Args:
        edge: Edge used by this operation.
        run_id: Identifier for run.

    Returns:
        Neo4jProjectionEdgeParameters result produced by edge parameters.
    """
    target_key = (
        f"{run_id}:note:{edge.target_note_id}"
        if edge.target_note_id is not None
        else f"{run_id}:path:{edge.target_path}"
    )
    return {
        "edge_id": edge.edge_id,
        "source_key": f"{run_id}:note:{edge.source_note_id}",
        "source_note_id": edge.source_note_id,
        "source_path": edge.source_path,
        "target_key": target_key,
        "target_note_id": edge.target_note_id,
        "target_path": edge.target_path,
        "relation": edge.relation.value,
        "confidence": edge.confidence,
        "source_kind": edge.source_kind.value,
    }


def _node_from_row(row: Neo4jProjectionRawRow) -> ObsidianGraphProjectionNode:
    """Execute node from row.

    Args:
        row: Row used by this operation.

    Returns:
        ObsidianGraphProjectionNode result produced by node from row.
    """
    return ObsidianGraphProjectionNode(
        note_id=_required_text(row, "note_id"),
        relative_path=_required_text(row, "relative_path"),
        alexandria_type=AlexandriaNoteType(_required_text(row, "alexandria_type")),
        title=_required_text(row, "title"),
        status=_required_text(row, "status"),
        project=_optional_text(row, "project"),
    )


def _edge_from_row(row: Neo4jProjectionRawRow) -> ObsidianGraphProjectionEdge:
    """Execute edge from row.

    Args:
        row: Row used by this operation.

    Returns:
        ObsidianGraphProjectionEdge result produced by edge from row.
    """
    confidence = row.get("confidence")
    if not isinstance(confidence, int | float):
        raise TypeError("Neo4j projection edge confidence must be numeric")
    return ObsidianGraphProjectionEdge(
        edge_id=_required_text(row, "edge_id"),
        source_note_id=_required_text(row, "source_note_id"),
        source_path=_required_text(row, "source_path"),
        target_note_id=_optional_text(row, "target_note_id"),
        target_path=_required_text(row, "target_path"),
        relation=ObsidianRelationType(_required_text(row, "relation")),
        confidence=float(confidence),
        source_kind=ObsidianEdgeSourceKind(_required_text(row, "source_kind")),
    )


def _related_note_from_row(row: Neo4jProjectionRawRow) -> ObsidianGraphRelatedNote:
    """Execute related note from row.

    Args:
        row: Row used by this operation.

    Returns:
        ObsidianGraphRelatedNote result produced by related note from row.
    """
    score = row.get("score")
    if not isinstance(score, int | float):
        raise TypeError("Neo4j related-note score must be numeric")
    return ObsidianGraphRelatedNote(
        note_id=_required_text(row, "related_note_id"),
        edge_id=_required_text(row, "edge_id"),
        relation=ObsidianRelationType(_required_text(row, "relation")),
        source_kind=ObsidianEdgeSourceKind(_required_text(row, "source_kind")),
        direction=ObsidianGraphDirection(_required_text(row, "direction")),
        score=float(score),
    )


def _context_evidence_from_row(
    row: Neo4jProjectionRawRow,
) -> ObsidianGraphContextEvidence:
    """Execute context evidence from row.

    Args:
        row: Row used by this operation.

    Returns:
        ObsidianGraphContextEvidence result produced by context evidence from row.
    """
    return ObsidianGraphContextEvidence(
        signal=ObsidianGraphContextSignalType(_required_text(row, "signal")),
        edge_id=_required_text(row, "edge_id"),
        source_note_id=_required_text(row, "source_note_id"),
        target_note_id=_required_text(row, "target_note_id"),
        target_title=_required_text(row, "target_title"),
        relation=ObsidianRelationType(_required_text(row, "relation")),
    )


def _required_text(row: Neo4jProjectionRawRow, key: str) -> str:
    """Execute required text.

    Args:
        row: Row used by this operation.
        key: Key used by this operation.

    Returns:
        str result produced by required text.
    """
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError(f"Neo4j projection row requires text field {key}")
    return value


def _optional_text(row: Neo4jProjectionRawRow, key: str) -> str | None:
    """Execute optional text.

    Args:
        row: Row used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by optional text.
    """
    value = row.get(key)
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"Neo4j projection row field {key} must be text or null")
