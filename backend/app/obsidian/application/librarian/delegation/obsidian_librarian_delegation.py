"""Provider-backed delegation helpers for Obsidian librarian asks."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.librarian.domain.contracts.hermes_collaboration_contracts import (
    HermesLibrarianAskCommand,
)
from app.librarian.domain.entities.source_ref import SourceRef
from app.librarian.domain.event_enum.source_ref_enums import SourceRefType
from app.librarian.domain.types.hermes_collaboration_payload_types import (
    HermesLibrarianAskPayload,
)
from app.obsidian.domain.contracts.obsidian_contracts import ObsidianLibrarianAsk
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.exceptions.librarian_exceptions import LibrarianResourceNotFoundError
from app.shared.types.extra_types import JSONObject, JSONValue

DELEGATE_SELECTION_MAX_CHARS = 4_000


class ObsidianLibrarianDelegateService(ABC):
    """Provider-backed librarian delegate boundary used by Obsidian asks."""

    @abstractmethod
    async def ask_librarian(
        self,
        command: HermesLibrarianAskCommand,
    ) -> HermesLibrarianAskPayload:
        """Ask the configured Hermes librarian delegate service.

        Args:
            command: Provider/profile-aware librarian command.

        Returns:
            Provider-backed librarian response payload.
        """


async def apply_provider_delegate(
    payload: ObsidianLibrarianAsk,
    response: JSONObject,
    delegate_service: ObsidianLibrarianDelegateService | None,
) -> None:
    """Mutate an Obsidian librarian response with provider-backed delegation.

    Args:
        payload: Original Obsidian librarian ask command.
        response: Local Obsidian-grounded response payload to enrich.
        delegate_service: Optional provider-backed delegate boundary.

    Returns:
        None.
    """
    if not payload.delegate_to_librarian:
        return
    if delegate_service is None:
        return
    try:
        delegate_payload = await delegate_service.ask_librarian(
            _delegate_command(payload, response)
        )
    except LibrarianResourceNotFoundError as exc:
        _append_unavailable_delegate_response(
            response,
            provider_id=payload.provider_id,
            profile_id=payload.profile_id,
            reason=str(exc),
        )
        return
    _append_delegate_response(response, delegate_payload)


def _delegate_command(
    payload: ObsidianLibrarianAsk,
    response: JSONObject,
) -> HermesLibrarianAskCommand:
    """Execute delegate command.

    Args:
        payload: Validated payload for this operation.
        response: Response value being processed.

    Returns:
        HermesLibrarianAskCommand result produced by delegate command.
    """
    return HermesLibrarianAskCommand(
        prompt=_delegate_prompt(payload, response),
        agent_name="obsidian-librarian",
        project=payload.project,
        task_summary=payload.query,
        delegate_to_librarian=True,
        provider_id=payload.provider_id,
        librarian_profile_id=payload.profile_id,
        librarian_model=None,
        librarian_role_prompt=None,
        max_librarian_agents=1,
        routing_specialties=("obsidian", "graph", "oauth", "gpt"),
        source_refs=_delegate_source_refs(response),
        librarian_brief=_delegate_brief(payload, response),
    )


def _delegate_prompt(
    payload: ObsidianLibrarianAsk,
    response: JSONObject,
) -> str:
    """Execute delegate prompt.

    Args:
        payload: Validated payload for this operation.
        response: Response value being processed.

    Returns:
        str result produced by delegate prompt.
    """
    return "\n\n".join(
        [
            "Answer the user's question using the Obsidian context packet below.",
            f"Question: {payload.query}",
            f"Active note: {payload.active_note_path or 'none'}",
            _selection_line(payload.selection),
            "If retrieved sources are empty, do not claim that no related notes exist; explain what context was used and what verification is still needed.",
            "Return the final answer, risks, missing sources, and graph/memory follow-up actions.",
            str(response.get("answer_markdown") or ""),
        ]
    )


def _delegate_brief(
    payload: ObsidianLibrarianAsk,
    response: JSONObject,
) -> str:
    """Execute delegate brief.

    Args:
        payload: Validated payload for this operation.
        response: Response value being processed.

    Returns:
        str result produced by delegate brief.
    """
    source_paths = [
        str(ref.get("path"))
        for ref in _response_source_ref_objects(response)
        if isinstance(ref.get("path"), str)
    ]
    return "\n".join(
        [
            "# Obsidian Librarian Answer Brief",
            "",
            "Use this packet to answer the user's question. Do not review a prewritten answer.",
            "If retrieved sources are empty, treat that as insufficient retrieval evidence, not proof that no related notes exist.",
            "",
            f"- query: {payload.query}",
            f"- project: {payload.project or 'default'}",
            f"- active_note_path: {payload.active_note_path or 'none'}",
            f"- selection_status: {_selection_status(payload.selection)}",
            f"- source_paths: {', '.join(source_paths) if source_paths else 'none'}",
            "",
            _selection_block(payload.selection),
            "",
            str(response.get("answer_markdown") or ""),
        ]
    )


def _delegate_source_refs(response: JSONObject) -> tuple[SourceRef, ...]:
    """Execute delegate source refs.

    Args:
        response: Response value being processed.

    Returns:
        tuple[SourceRef, ...] result produced by delegate source refs.
    """
    refs: list[SourceRef] = []
    for item in _response_source_ref_objects(response):
        note_id = item.get("id")
        path = item.get("path")
        title = item.get("title")
        if not isinstance(note_id, str) or not isinstance(path, str):
            continue
        refs.append(
            SourceRef(
                source_type=_source_ref_type(item.get("alexandria_type")),
                source_id=note_id,
                title=title if isinstance(title, str) and title else path,
                detail_path=f"/obsidian/notes/{note_id}",
                preview=path,
            )
        )
    return tuple(refs)


def _response_source_ref_objects(response: JSONObject) -> list[JSONObject]:
    """Execute response source ref objects.

    Args:
        response: Response value being processed.

    Returns:
        list[JSONObject] result produced by response source ref objects.
    """
    value = response.get("source_refs")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _source_ref_type(alexandria_type: JSONValue | None) -> SourceRefType:
    """Execute source ref type.

    Args:
        alexandria_type: Alexandria type used by this operation.

    Returns:
        SourceRefType result produced by source ref type.
    """
    if alexandria_type == AlexandriaNoteType.MEMORY_COMPACT.value:
        return SourceRefType.MEMORY_COMPACT
    if alexandria_type == AlexandriaNoteType.SKILL.value:
        return SourceRefType.SKILL
    if alexandria_type == AlexandriaNoteType.PROMPT.value:
        return SourceRefType.PROMPT
    if alexandria_type == AlexandriaNoteType.CONTEXT.value:
        return SourceRefType.CONTEXT
    return SourceRefType.LIBRARY_ITEM


def _append_delegate_response(
    response: JSONObject,
    delegate_payload: HermesLibrarianAskPayload,
) -> None:
    """Execute append delegate response.

    Args:
        response: Response value being processed.
        delegate_payload: Delegate payload used by this operation.
    """
    status = _string_value(delegate_payload["status"])
    response["delegate_status"] = status
    response["provider_id"] = _optional_string_value(delegate_payload["provider_id"])
    response["profile_id"] = _optional_string_value(
        delegate_payload["librarian_profile_id"]
    )
    _append_action_preview(response, f"delegate_librarian:{status}")
    _append_delegate_summary(response, delegate_payload)


def _append_unavailable_delegate_response(
    response: JSONObject,
    provider_id: str | None,
    profile_id: str | None,
    reason: str,
) -> None:
    """Execute append unavailable delegate response.

    Args:
        response: Response value being processed.
        provider_id: Identifier for provider.
        profile_id: Identifier for profile.
        reason: Reason used by this operation.
    """
    response["delegate_status"] = "GUIDANCE_ONLY"
    response["provider_id"] = provider_id
    response["profile_id"] = profile_id
    _append_action_preview(response, "delegate_librarian:GUIDANCE_ONLY")
    _append_answer_section(response, "GPT OAuth Librarian", reason)


def _append_delegate_summary(
    response: JSONObject,
    delegate_payload: HermesLibrarianAskPayload,
) -> None:
    """Execute append delegate summary.

    Args:
        response: Response value being processed.
        delegate_payload: Delegate payload used by this operation.
    """
    summaries: list[str] = []
    for item in delegate_payload["delegates"]:
        summary = item.get("summary")
        if isinstance(summary, str) and summary.strip():
            summaries.append(summary.strip())
    if not summaries:
        recommendation = delegate_payload.get("recommendation")
        if isinstance(recommendation, str) and recommendation.strip():
            summaries.append(recommendation.strip())
    if not summaries:
        return
    _append_answer_section(response, "GPT OAuth Librarian", "\n\n".join(summaries))


def _append_answer_section(response: JSONObject, heading: str, body: str) -> None:
    """Execute append answer section.

    Args:
        response: Response value being processed.
        heading: Heading used by this operation.
        body: Body used by this operation.
    """
    answer = str(response.get("answer_markdown") or "")
    response["answer_markdown"] = "\n\n".join([answer, f"## {heading}", body])


def _append_action_preview(response: JSONObject, item: str) -> None:
    """Execute append action preview.

    Args:
        response: Response value being processed.
        item: Item being processed.
    """
    value = response.get("action_preview")
    if not isinstance(value, list):
        response["action_preview"] = [item]
        return
    if item in value:
        return
    value.append(item)


def _string_value(value: JSONValue) -> str:
    """Execute string value.

    Args:
        value: Value being processed.

    Returns:
        str result produced by string value.
    """
    return value if isinstance(value, str) else str(value)


def _optional_string_value(value: JSONValue | None) -> str | None:
    """Execute optional string value.

    Args:
        value: Value being processed.

    Returns:
        str | None result produced by optional string value.
    """
    return value if isinstance(value, str) and value else None


def _selection_status(selection: str | None) -> str:
    """Execute selection status.

    Args:
        selection: Selection used by this operation.

    Returns:
        str result produced by selection status.
    """
    return "ingested" if selection is not None and selection.strip() else "none"


def _selection_line(selection: str | None) -> str:
    """Execute selection line.

    Args:
        selection: Selection used by this operation.

    Returns:
        str result produced by selection line.
    """
    if selection is None or not selection.strip():
        return "Selection: none"
    return f"Selection provided:\n{_selection_excerpt(selection)}"


def _selection_block(selection: str | None) -> str:
    """Execute selection block.

    Args:
        selection: Selection used by this operation.

    Returns:
        str result produced by selection block.
    """
    if selection is None or not selection.strip():
        return "## Selection\nnone"
    return f"## Selection\n{_selection_excerpt(selection)}"


def _selection_excerpt(selection: str) -> str:
    """Execute selection excerpt.

    Args:
        selection: Selection used by this operation.

    Returns:
        str result produced by selection excerpt.
    """
    normalized = selection.strip()
    if len(normalized) <= DELEGATE_SELECTION_MAX_CHARS:
        return normalized
    return f"{normalized[:DELEGATE_SELECTION_MAX_CHARS]}\n…[selection truncated]"
