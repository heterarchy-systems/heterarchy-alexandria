"""Context facade lint behavior."""

from __future__ import annotations

from app.memory.application.contexts.linting.context_lint import ContextLintResult
from app.memory.application.contexts.linting.context_lint_service import (
    ContextLintService,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextScope,
    MemoryFunction,
)


class ContextServiceLintMixin:
    """Expose Context Harness linting through the stable facade."""

    _lint_service: ContextLintService

    def lint(
        self,
        kind: ContextKind,
        title: str,
        content: str,
        summary: str | None,
        project: str | None,
        memory_function: MemoryFunction | None = None,
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
            memory_function: Optional functional role for this memory.
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
        return self._lint_service.lint(
            kind=kind,
            memory_function=memory_function,
            title=title,
            content=content,
            summary=summary,
            project=project,
            scope=scope,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            visibility=visibility,
            source_agent=source_agent,
            tags=tags,
        )
