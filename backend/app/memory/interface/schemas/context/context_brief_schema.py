from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.memory.domain.event_enum.context_enums import RagStrategy
from app.memory.domain.types.context_payload_types import (
    MAX_CONTEXT_BRIEF_BYTES,
    MAX_CONTEXTS_PER_BRIEF,
)
from app.memory.interface.schemas.context.context_search_schema import (
    ContextSearchRequest,
)
from app.shared.schemas.common_schemas import StrictSchemaModel, schema_list_default

_DeliveredIdentityKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ContextBriefRequest(ContextSearchRequest):
    """Request payload for one budgeted model-delivery context brief.

    Runs the same retrieval path as the Context Pack and derives a
    byte-budgeted brief with repetition suppression driven by the
    ``previously_delivered`` ``(context_id, content_hash)`` pairs.
    """

    byte_budget: Annotated[
        int,
        Field(
            description="Maximum rendered utf-8 byte count for this brief.",
            ge=1,
            le=MAX_CONTEXT_BRIEF_BYTES,
        ),
    ] = MAX_CONTEXT_BRIEF_BYTES
    record_budget: Annotated[
        int,
        Field(
            description="Maximum number of delivered context entries for this brief.",
            ge=1,
            le=MAX_CONTEXTS_PER_BRIEF,
        ),
    ] = MAX_CONTEXTS_PER_BRIEF
    previously_delivered: Annotated[
        list[tuple[_DeliveredIdentityKey, _DeliveredIdentityKey]],
        Field(
            description="Ordered ``(context_id, content_hash)`` pairs delivered to the "
            "same consumer by earlier briefs; unchanged pairs are suppressed "
            "into already-delivered markers."
        ),
    ] = schema_list_default()


class ContextRefetchReferenceResponse(StrictSchemaModel):
    """Exact re-fetch reference through the existing retrieval API."""

    context_id: Annotated[
        str, Field(description="Context identifier to re-fetch for this reference.")
    ]
    canonical_context_id: Annotated[
        str,
        Field(
            description="Canonical context identifier to re-fetch for this reference."
        ),
    ]
    query: Annotated[
        str, Field(description="Query to re-run for this re-fetch reference.")
    ]
    retrieval_strategy: Annotated[
        RagStrategy,
        Field(description="Retrieval strategy for this re-fetch reference."),
    ]
    chunk_id: Annotated[
        str | None,
        Field(description="Chunk identifier for this re-fetch reference when known."),
    ]
    evidence_refs: Annotated[
        list[str],
        Field(description="Evidence references for this re-fetch reference."),
    ]


class ContextBriefSectionResponse(StrictSchemaModel):
    """One delivered HANDOFF-style section inside a brief entry."""

    heading: Annotated[
        str, Field(description="Section heading for this brief section response.")
    ]
    text: Annotated[
        str,
        Field(description="Delivered section text for this brief section response."),
    ]
    truncated: Annotated[
        bool,
        Field(
            description="Whether this section text is a truncated prefix of the source section."
        ),
    ]
    delivered_bytes: Annotated[
        int,
        Field(
            description="Exact utf-8 byte count delivered for this brief section response.",
            ge=0,
        ),
    ]


class ContextBriefEntryResponse(StrictSchemaModel):
    """One delivered source context inside a brief.

    Entries reference their source Context for re-fetch and suppression
    semantics only; they never embed a Context payload.
    """

    context_id: Annotated[
        str, Field(description="Source context identifier for this brief entry.")
    ]
    title: Annotated[
        str, Field(description="Source context title for this brief entry.")
    ]
    score: Annotated[float, Field(description="Retrieval score for this brief entry.")]
    content_hash: Annotated[
        str, Field(description="Delivered chunk content hash for this brief entry.")
    ]
    delivery_status: Annotated[
        Literal["new", "changed"],
        Field(
            description="Whether this brief entry is new or changed since the last delivery."
        ),
    ]
    sections: Annotated[
        list[ContextBriefSectionResponse],
        Field(description="Delivered sections for this brief entry."),
    ]


class ContextBriefAlreadyDeliveredResponse(StrictSchemaModel):
    """Compact marker replacing one unchanged previously delivered entry."""

    context_id: Annotated[
        str, Field(description="Context identifier suppressed by this marker.")
    ]
    content_hash: Annotated[
        str, Field(description="Unchanged content hash suppressed by this marker.")
    ]
    refetch: Annotated[
        ContextRefetchReferenceResponse,
        Field(description="Re-fetch reference for this already delivered marker."),
    ]


class ContextBriefOmissionResponse(StrictSchemaModel):
    """One omitted or truncated brief item with its re-fetch reference."""

    context_id: Annotated[
        str, Field(description="Source context identifier for this omission.")
    ]
    reason: Annotated[
        Literal["record_budget", "byte_budget", "section_truncated"],
        Field(description="Why this item is not delivered in full."),
    ]
    heading: Annotated[
        str | None,
        Field(description="Section heading when this omission is section-scoped."),
    ]
    refetch: Annotated[
        ContextRefetchReferenceResponse,
        Field(description="Exact re-fetch reference for this omission."),
    ]


class ContextBriefResponse(StrictSchemaModel):
    """Budgeted model-delivery brief with repetition suppression.

    Identity-free by contract: the brief carries no id and no embedded
    Context payload, so brief output cannot re-enter retrieval as a Context.
    """

    query: Annotated[str, Field(description="Query for this context brief response.")]
    byte_budget: Annotated[
        int,
        Field(description="Maximum rendered utf-8 byte count for this brief.", ge=0),
    ]
    record_budget: Annotated[
        int,
        Field(
            description="Maximum number of delivered context entries for this brief.",
            ge=0,
        ),
    ]
    total_bytes: Annotated[
        int,
        Field(
            description="Exact utf-8 byte length of the rendered context_brief field.",
            ge=0,
        ),
    ]
    estimated_tokens: Annotated[
        int,
        Field(
            description="Estimated token count for context_brief (utf-8 characters divided "
            "by four; a labeled rough estimate, not a tokenizer count).",
            ge=0,
        ),
    ]
    entries: Annotated[
        list[ContextBriefEntryResponse],
        Field(description="Delivered entries for this context brief response."),
    ]
    already_delivered: Annotated[
        list[ContextBriefAlreadyDeliveredResponse],
        Field(
            description="Markers for entries suppressed as unchanged since their last delivery."
        ),
    ]
    omitted: Annotated[
        list[ContextBriefOmissionResponse],
        Field(
            description="Omitted or truncated items with their exact re-fetch references."
        ),
    ]
    context_brief: Annotated[
        str,
        Field(description="Rendered brief markdown for this context brief response."),
    ]
