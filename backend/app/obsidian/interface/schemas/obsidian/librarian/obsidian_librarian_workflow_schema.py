"""HTTP schemas for Obsidian librarian ask/workflow operations."""

from __future__ import annotations

from typing import Annotated

from pydantic import field_validator

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianLibrarianAsk
from app.obsidian.domain.entities.obsidian_note import ObsidianLibrarianWorkflow
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianLibrarianWorkflowStatus,
)
from app.obsidian.interface.schemas.obsidian.librarian.obsidian_librarian_type_aliases import (
    preferred_note_type_input,
)
from app.obsidian.interface.schemas.obsidian.obsidian_string_types import (
    ObsidianQueryText,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)
from app.shared.types.extra_types import JSONObject, JSONValue


class ObsidianLibrarianAskRequest(StrictSchemaModel):
    """Ask the Obsidian-aware Alexandria librarian."""

    query: Annotated[
        ObsidianQueryText,
        described_field("Query for this Obsidian librarian ask request."),
    ]
    active_note_path: Annotated[
        str | None,
        described_field("Active note path for this Obsidian librarian ask request."),
    ] = None
    selection: Annotated[
        str | None,
        described_field("Selection for this Obsidian librarian ask request."),
    ] = None
    project: Annotated[
        str | None, described_field("Project for this Obsidian librarian ask request.")
    ] = None
    preferred_alexandria_types: Annotated[
        list[AlexandriaNoteType],
        described_field(
            "Preferred alexandria types for this Obsidian librarian ask request."
        ),
    ] = schema_list_default()
    max_source_refs: Annotated[
        int,
        described_field(
            "Max source refs for this Obsidian librarian ask request.", ge=1, le=50
        ),
    ] = 12
    save_transcript: Annotated[
        bool,
        described_field("Save transcript for this Obsidian librarian ask request."),
    ] = False
    delegate_to_librarian: Annotated[
        bool,
        described_field(
            "Delegate to librarian for this Obsidian librarian ask request."
        ),
    ] = False
    provider_id: Annotated[
        str | None,
        described_field("Provider identifier for this Obsidian librarian ask request."),
    ] = None
    profile_id: Annotated[
        str | None,
        described_field("Profile identifier for this Obsidian librarian ask request."),
    ] = None

    @field_validator("preferred_alexandria_types", mode="before")
    @classmethod
    def normalize_preferred_alexandria_types(cls, value: JSONValue) -> JSONValue:
        """Normalize agent-facing note type aliases before enum validation.

        MCP callers provide this field as free strings. The Obsidian shelf named
        "Indexes" stores notes as Alexandria context notes, so accepting
        "index" avoids a brittle 422 for otherwise valid librarian requests.

        Args:
            value: Raw Pydantic input value before enum validation.

        Returns:
            Normalized value for downstream enum validation.
        """
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [preferred_note_type_input(item) for item in value]

    def to_command(self) -> ObsidianLibrarianAsk:
        """Convert request into application command.

        Returns:
            Application librarian ask command.
        """
        return ObsidianLibrarianAsk(
            query=self.query,
            active_note_path=self.active_note_path,
            selection=self.selection,
            project=self.project,
            preferred_alexandria_types=tuple(
                _note_type(note_type) for note_type in self.preferred_alexandria_types
            ),
            max_source_refs=self.max_source_refs,
            save_transcript=self.save_transcript,
            delegate_to_librarian=self.delegate_to_librarian,
            provider_id=self.provider_id,
            profile_id=self.profile_id,
        )


class ObsidianSourceRefResponse(StrictSchemaModel):
    """Source reference returned from an Obsidian librarian answer."""

    id: Annotated[
        str, described_field("Stable identifier for this Obsidian source ref response.")
    ]
    alexandria_type: Annotated[
        str, described_field("Alexandria type for this Obsidian source ref response.")
    ]
    path: Annotated[str, described_field("Path for this Obsidian source ref response.")]
    title: Annotated[
        str, described_field("Title for this Obsidian source ref response.")
    ]
    wikilink: Annotated[
        str, described_field("Wikilink for this Obsidian source ref response.")
    ]


class ObsidianLibrarianAskResponse(StrictSchemaModel):
    """Response from the Obsidian-aware librarian adapter."""

    answer_markdown: Annotated[
        str,
        described_field("Answer markdown for this Obsidian librarian ask response."),
    ]
    source_refs: Annotated[
        list[ObsidianSourceRefResponse],
        described_field("Source refs for this Obsidian librarian ask response."),
    ]
    input_context: Annotated[
        JSONObject,
        described_field("Input context for this Obsidian librarian ask response."),
    ]
    context_status: Annotated[
        str, described_field("Context status for this Obsidian librarian ask response.")
    ]
    action_preview: Annotated[
        list[str],
        described_field("Action preview for this Obsidian librarian ask response."),
    ]
    conversation_id: Annotated[
        str,
        described_field(
            "Conversation identifier for this Obsidian librarian ask response."
        ),
    ]
    transcript_path: Annotated[
        str | None,
        described_field("Transcript path for this Obsidian librarian ask response."),
    ]
    delegate_status: Annotated[
        str,
        described_field("Delegate status for this Obsidian librarian ask response."),
    ] = "local_only"
    provider_id: Annotated[
        str | None,
        described_field(
            "Provider identifier for this Obsidian librarian ask response."
        ),
    ] = None
    profile_id: Annotated[
        str | None,
        described_field("Profile identifier for this Obsidian librarian ask response."),
    ] = None


class ObsidianLibrarianWorkflowResumeRequest(StrictSchemaModel):
    """Approved actions for resuming a librarian workflow."""

    approved_actions: Annotated[
        list[str],
        described_field(
            "Approved actions for this Obsidian librarian workflow resume request."
        ),
    ] = schema_list_default()


class ObsidianLibrarianWorkflowResponse(StrictSchemaModel):
    """Resumable librarian workflow response."""

    thread_id: Annotated[
        str,
        described_field(
            "Thread identifier for this Obsidian librarian workflow response."
        ),
    ]
    status: Annotated[
        ObsidianLibrarianWorkflowStatus,
        described_field("Status for this Obsidian librarian workflow response."),
    ]
    query: Annotated[
        str, described_field("Query for this Obsidian librarian workflow response.")
    ]
    active_note_path: Annotated[
        str | None,
        described_field(
            "Active note path for this Obsidian librarian workflow response."
        ),
    ]
    project: Annotated[
        str | None,
        described_field("Project for this Obsidian librarian workflow response."),
    ]
    provider_id: Annotated[
        str | None,
        described_field(
            "Provider identifier for this Obsidian librarian workflow response."
        ),
    ]
    profile_id: Annotated[
        str | None,
        described_field(
            "Profile identifier for this Obsidian librarian workflow response."
        ),
    ]
    delegate_requested: Annotated[
        bool,
        described_field(
            "Delegate requested for this Obsidian librarian workflow response."
        ),
    ]
    response: Annotated[
        JSONObject,
        described_field("Response for this Obsidian librarian workflow response."),
    ]
    pending_actions: Annotated[
        list[JSONObject],
        described_field(
            "Pending actions for this Obsidian librarian workflow response."
        ),
    ]
    approved_actions: Annotated[
        list[str],
        described_field(
            "Approved actions for this Obsidian librarian workflow response."
        ),
    ]
    completed_actions: Annotated[
        list[str],
        described_field(
            "Completed actions for this Obsidian librarian workflow response."
        ),
    ]
    transcript_path: Annotated[
        str | None,
        described_field(
            "Transcript path for this Obsidian librarian workflow response."
        ),
    ]

    @classmethod
    def from_entity(
        cls, workflow: ObsidianLibrarianWorkflow
    ) -> ObsidianLibrarianWorkflowResponse:
        """Create schema from workflow checkpoint.

        Args:
            workflow: Persisted workflow checkpoint.

        Returns:
            HTTP workflow schema.
        """
        state = workflow.state
        return cls(
            thread_id=workflow.thread_id,
            status=workflow.status,
            query=workflow.query,
            active_note_path=workflow.active_note_path,
            project=workflow.project,
            provider_id=workflow.provider_id,
            profile_id=workflow.profile_id,
            delegate_requested=workflow.delegate_requested,
            response=_object_list_safe(state, "response"),
            pending_actions=_json_object_list(state, "pending_actions"),
            approved_actions=_string_list(state, "approved_actions"),
            completed_actions=_string_list(state, "completed_actions"),
            transcript_path=_optional_string(state.get("transcript_path")),
        )


def _object_list_safe(state: JSONObject, key: str) -> JSONObject:
    """Execute object list safe.

    Args:
        state: State used by this operation.
        key: Key used by this operation.

    Returns:
        JSONObject result produced by object list safe.
    """
    value = state.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _json_object_list(state: JSONObject, key: str) -> list[JSONObject]:
    """Execute json object list.

    Args:
        state: State used by this operation.
        key: Key used by this operation.

    Returns:
        list[JSONObject] result produced by json object list.
    """
    value = state.get(key)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(state: JSONObject, key: str) -> list[str]:
    """Execute string list.

    Args:
        state: State used by this operation.
        key: Key used by this operation.

    Returns:
        list[str] result produced by string list.
    """
    value = state.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _optional_string(value: JSONValue | None) -> str | None:
    """Execute optional string.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by optional string.
    """
    return value if isinstance(value, str) and value else None


def _note_type(value: AlexandriaNoteType | str) -> AlexandriaNoteType:
    """Execute note type.

    Args:
        value: Value being processed.

    Returns:
        AlexandriaNoteType result produced by note type.
    """
    if isinstance(value, AlexandriaNoteType):
        return value
    return AlexandriaNoteType(value)
