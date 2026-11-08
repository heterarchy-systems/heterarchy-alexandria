"""HTTP/MCP contracts for graph orphan census and suggestions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.shared.schemas.common_schemas import StrictSchemaModel, exclude_none_field


class ObsidianGraphOrphanListRequest(StrictSchemaModel):
    """One bounded orphan census page request."""

    project: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=255),
        Field(description="Optional project filter."),
        exclude_none_field(),
    ] = None
    limit: Annotated[
        int, Field(description="Maximum orphans on this page.", ge=1, le=200)
    ] = 50
    cursor: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=2048),
        Field(description="Last path from the previous page."),
        exclude_none_field(),
    ] = None


class ObsidianGraphOrphanStatusRequest(StrictSchemaModel):
    """Exact note-id lookup for current orphan debt and history."""

    note_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        Field(description="Exact orphan note identifier."),
    ]


class ObsidianGraphOrphanEntryResponse(StrictSchemaModel):
    """One degree-zero node with its census status."""

    note_id: Annotated[str, Field(description="Orphan note identifier.")]
    relative_path: Annotated[str, Field(description="Canonical managed path.")]
    title: Annotated[str, Field(description="Canonical note title.")]
    project: Annotated[
        str | None,
        Field(description="Project identity when declared."),
        exclude_none_field(),
    ] = None
    status: Annotated[
        str,
        Field(
            description="OPEN, RESOLVED, ACKNOWLEDGED_STANDALONE, or IGNORED_WITH_REASON."
        ),
    ]
    in_degree: Annotated[int | None, Field(description="Projection in-degree.")] = None
    out_degree: Annotated[int | None, Field(description="Projection out-degree.")] = (
        None
    )
    canonical_parent_count: Annotated[
        int | None, Field(description="Incoming canonical contains-parent count.")
    ] = None
    has_wikilink_connectivity: Annotated[
        bool | None,
        Field(
            description="Whether wikilink-only connectivity exists without canonical parent ownership."
        ),
    ] = None
    debt_kinds: Annotated[list[str], Field(description="Measured orphan debt classes.")]
    has_declared_relations: Annotated[
        bool | None,
        Field(
            description="Whether the note still declares relation frontmatter, so the "
            "orphan is an unresolved-declared-link case."
        ),
    ] = None
    acknowledgement_reason: Annotated[
        str | None,
        Field(description="Reason recorded with the acknowledgement."),
        exclude_none_field(),
    ] = None
    first_seen_at: Annotated[
        str | None,
        Field(description="First durable census observation timestamp."),
        exclude_none_field(),
    ] = None
    last_seen_at: Annotated[
        str | None,
        Field(description="Latest durable census observation timestamp."),
        exclude_none_field(),
    ] = None
    first_seen_run_id: Annotated[
        str | None,
        Field(description="Run that first observed this orphan."),
        exclude_none_field(),
    ] = None
    last_seen_run_id: Annotated[
        str | None,
        Field(description="Most recent run that observed this orphan."),
        exclude_none_field(),
    ] = None
    graph_run_id: Annotated[
        str | None,
        Field(description="Projection run associated with the latest observation."),
        exclude_none_field(),
    ] = None


class ObsidianGraphOrphanCensusResponse(StrictSchemaModel):
    """One graph debt census page with stable pagination."""

    orphans: Annotated[
        list[ObsidianGraphOrphanEntryResponse],
        Field(description="Orphans in path order for this page."),
    ]
    total_orphans: Annotated[
        int, Field(description="Total measured degree-zero or missing-parent debt.")
    ]
    next_cursor: Annotated[
        str | None,
        Field(description="Cursor for the next page when more orphans exist."),
        exclude_none_field(),
    ] = None


class ObsidianGraphOrphanAcknowledgeRequest(StrictSchemaModel):
    """One durable census acknowledgement."""

    note_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=255),
        Field(description="Orphan note identifier."),
    ]
    decision: Annotated[
        Literal["ACKNOWLEDGED_STANDALONE", "IGNORED_WITH_REASON"],
        Field(description="Census decision for this standalone note."),
    ]
    reason: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=1000),
        Field(description="Required reason for IGNORED_WITH_REASON."),
        exclude_none_field(),
    ] = None
    acknowledged_by: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
        Field(description="Actor label recorded for provenance."),
    ] = "agent"


class ObsidianGraphSuggestRelationsRequest(StrictSchemaModel):
    """One deterministic relation suggestion request."""

    note_id: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=255),
        Field(description="Seed note identifier; requires note_id or path."),
        exclude_none_field(),
    ] = None
    path: Annotated[
        str | None,
        StringConstraints(strict=True, min_length=1, max_length=2048),
        Field(description="Seed note vault-relative path; requires note_id or path."),
        exclude_none_field(),
    ] = None
    limit: Annotated[int, Field(description="Maximum suggestions.", ge=1, le=50)] = 10


class ObsidianGraphRelationSuggestionResponse(StrictSchemaModel):
    """One evidence-backed relation candidate."""

    candidate_note_id: Annotated[str, Field(description="Candidate note identifier.")]
    candidate_path: Annotated[str, Field(description="Candidate managed path.")]
    candidate_title: Annotated[str, Field(description="Candidate title.")]
    relation: Annotated[
        str, Field(description="Proposed relation type (suggestion only).")
    ]
    confidence: Annotated[
        float, Field(description="Deterministic evidence score, bounded 0..1.")
    ]
    shared_tags: Annotated[
        list[str], Field(description="Tags shared with the seed note.")
    ]
    shared_neighbor_count: Annotated[
        int, Field(description="Shared one-hop graph neighbors.")
    ]
    title_overlap_tokens: Annotated[
        list[str], Field(description="Title tokens shared with the seed note.")
    ]
    explanation: Annotated[
        str, Field(description="Bounded deterministic evidence explanation.")
    ]


class ObsidianGraphRelationSuggestionsResponse(StrictSchemaModel):
    """Deterministic suggestions for one seed note."""

    note_id: Annotated[str, Field(description="Seed note identifier.")]
    relative_path: Annotated[str, Field(description="Seed note managed path.")]
    suggestions: Annotated[
        list[ObsidianGraphRelationSuggestionResponse],
        Field(description="Suggestions ordered by confidence then path."),
    ]
