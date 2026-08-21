"""Context Harness lint input normalization service."""

from __future__ import annotations

from app.memory.application.contexts.linting.context_lint import (
    ContextLintInput,
    ContextLintResult,
    lint_context,
)
from app.memory.domain.event_enum.context_enums import ContextKind, ContextScope
from app.shared.types.types_convert_utils import enum_value


class ContextLintService:
    """Normalize one Context draft and run the deterministic Harness linter."""

    def lint(
        self,
        kind: ContextKind,
        title: str,
        content: str,
        summary: str | None,
        project: str | None,
        scope: ContextScope = ContextScope.PROJECT,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        visibility: ContextScope = ContextScope.PROJECT,
        source_agent: str = "Hermes",
        tags: list[str] | None = None,
    ) -> ContextLintResult:
        """Run Context Harness linting without persistence.

        Args:
            kind: Context entry kind.
            title: Human-readable title.
            content: Markdown content.
            summary: Optional summary supplied by the caller.
            project: Optional project scope.
            scope: Recall-routing scope.
            workspace_id: Optional workspace identifier.
            agent_id: Optional agent identifier.
            user_id: Optional user identifier.
            session_id: Optional session identifier.
            visibility: Recall visibility scope.
            source_agent: Agent that produced the content.
            tags: Caller-provided tags.

        Returns:
            Context lint result with redaction and quality details.
        """
        return lint_context(
            ContextLintInput(
                kind=enum_value(kind, ContextKind, "kind"),
                title=title,
                content=content,
                summary=summary,
                project=project,
                scope=enum_value(scope, ContextScope, "scope"),
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                visibility=enum_value(
                    visibility,
                    ContextScope,
                    "visibility",
                ),
                source_agent=source_agent,
                tags=() if tags is None else tuple(tags),
            )
        )
