"""Strict metadata validation for canonical managed-spec notes."""

from __future__ import annotations

from app.obsidian.application.service.managed_spec.managed_spec_failures import (
    _failure,
    _metadata_conflict,
)
from app.obsidian.application.service.managed_spec.managed_spec_source_values import (
    _normalize_workflow,
)
from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecExecutionContext,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.managed_spec_enums import (
    ManagedSpecFailureCode,
)
from app.obsidian.domain.event_enum.obsidian_enums import (
    AlexandriaNoteType,
    ObsidianIndexStatus,
)

_ACTIVE_STATUSES = frozenset({"active", "current"})
_POLICY_DOCUMENT_TYPE = "policy"
_SPEC_DOCUMENT_TYPE = "execution_prompt"
_SCHEDULER_POLICY_KIND = "scheduler-runtime"
_NOTE_IDENTITY_MODEL = "note_id_only"
_NOTE_ID_RUNTIME_SELECTOR = "note_id"


class ManagedSpecMetadataValidator:
    """Validate lifecycle and frontmatter for pinned policy/spec notes."""

    def validate_policy(
        self,
        note: ObsidianNote,
        context: ManagedSpecExecutionContext,
    ) -> int:
        """Validate the scheduler runtime policy declaration."""
        self.validate_note_ready(note=note, role="runtime policy")
        if self.metadata_text(note=note, key="document_type") != _POLICY_DOCUMENT_TYPE:
            raise _metadata_conflict(cause="runtime policy document_type is not policy")
        if self.metadata_text(note=note, key="policy_kind") != _SCHEDULER_POLICY_KIND:
            raise _metadata_conflict(
                cause="runtime policy policy_kind is not scheduler-runtime"
            )
        if not self.metadata_bool(note=note, key="canonical") or not self.metadata_bool(
            note=note,
            key="source_of_truth",
        ):
            raise _metadata_conflict(
                cause="runtime policy is not canonical source_of_truth"
            )
        if self.metadata_text(note=note, key="identity_model") != _NOTE_IDENTITY_MODEL:
            raise _metadata_conflict(
                cause="runtime policy identity_model must be note_id_only"
            )
        if (
            self.metadata_text(note=note, key="runtime_selector")
            != _NOTE_ID_RUNTIME_SELECTOR
        ):
            raise _metadata_conflict(
                cause="runtime policy runtime_selector must be note_id"
            )
        if note.note_id != context.expected_policy_note_id:
            raise _metadata_conflict(
                cause="runtime policy note id does not match trusted context"
            )
        return self.metadata_version(note=note, role="runtime policy")

    def validate_spec(
        self,
        note: ObsidianNote,
        context: ManagedSpecExecutionContext,
        policy_note_id: str,
    ) -> tuple[int, str]:
        """Validate the execution prompt and its exact policy linkage."""
        self.validate_note_ready(note=note, role="execution specification")
        if self.metadata_text(note=note, key="document_type") != _SPEC_DOCUMENT_TYPE:
            raise _metadata_conflict(
                cause="execution specification document_type is invalid"
            )
        if self.metadata_text(note=note, key="prompt_role") != "execution":
            raise _metadata_conflict(
                cause="execution specification prompt_role is invalid"
            )
        if not self.metadata_bool(note=note, key="canonical") or not self.metadata_bool(
            note=note,
            key="source_of_truth",
        ):
            raise _metadata_conflict(
                cause="execution specification is not canonical source_of_truth"
            )
        linked_policy = self.metadata_text(note=note, key="runtime_policy_note_id")
        if linked_policy != policy_note_id:
            raise _metadata_conflict(
                cause="execution specification runtime policy link conflicts"
            )
        workflow = self.metadata_text(note=note, key="report")
        if _normalize_workflow(workflow) != _normalize_workflow(context.workflow):
            raise _metadata_conflict(
                cause="execution specification workflow conflicts with context"
            )
        if "execution_spec_note_id" in note.frontmatter:
            declared = note.frontmatter.get("execution_spec_note_id")
            if declared is not None and not isinstance(declared, str):
                raise _metadata_conflict(
                    cause="execution specification selector metadata is invalid"
                )
            if isinstance(declared, str) and declared != note.note_id:
                raise _metadata_conflict(
                    cause=(
                        "execution specification selector metadata conflicts with exact note id"
                    )
                )
        return self.metadata_version(
            note=note, role="execution specification"
        ), workflow

    def validate_note_ready(self, note: ObsidianNote, role: str) -> None:
        """Check source type, lifecycle, index freshness, and body presence."""
        if note.alexandria_type is not AlexandriaNoteType.PROMPT:
            raise _metadata_conflict(cause=f"{role} must be an Alexandria prompt note")
        if note.status.strip().casefold() not in _ACTIVE_STATUSES:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_READY,
                cause=f"{role} is not active or current",
                retryable=False,
                safe_next_action="restore the canonical note to active/current status",
                recommended_action="repair_note_lifecycle",
            )
        if note.index_status is not ObsidianIndexStatus.INDEXED:
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_READY,
                cause=f"{role} index is not current",
                retryable=True,
                safe_next_action="reindex the canonical vault and retry",
                recommended_action="reindex_then_retry",
            )
        if not note.body.strip():
            raise _failure(
                code=ManagedSpecFailureCode.SPEC_NOT_READY,
                cause=f"{role} body is empty",
                retryable=False,
                safe_next_action="restore the canonical note body",
                recommended_action="repair_note_body",
            )

    def metadata_text(self, note: ObsidianNote, key: str) -> str:
        """Read one required string metadata value without coercion."""
        value = note.frontmatter.get(key)
        if not isinstance(value, str) or not value.strip():
            raise _metadata_conflict(
                cause=f"required metadata {key} is missing or untyped"
            )
        return value.strip()

    def metadata_bool(self, note: ObsidianNote, key: str) -> bool:
        """Read one required strict boolean metadata value."""
        value = note.frontmatter.get(key)
        if not isinstance(value, bool):
            raise _metadata_conflict(
                cause=f"required metadata {key} is missing or untyped"
            )
        return value

    def metadata_version(self, note: ObsidianNote, role: str) -> int:
        """Read one positive integer source revision."""
        value = note.frontmatter.get("version")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise _metadata_conflict(cause=f"{role} version is missing or untyped")
        return value
