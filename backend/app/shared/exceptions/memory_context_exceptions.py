"""Domain exceptions for Context Vault bounded-context use cases."""

from __future__ import annotations


class MemoryContextDomainError(RuntimeError):
    """Base Context Vault domain exception."""


class MemoryContextNotFoundError(MemoryContextDomainError):
    """Raised when a Context Vault resource cannot be located."""


class MemoryContextValidationError(MemoryContextDomainError):
    """Raised when a Context Vault invariant is violated."""


class ContextChangeCursorInvalidError(MemoryContextDomainError):
    """Raised when a change-log cursor token is malformed or structurally unknown."""


class ContextChangeCursorResyncRequiredError(MemoryContextDomainError):
    """Raised when a structurally valid cursor has an unsupported version or scope."""


class MemoryContextBriefBudgetError(MemoryContextDomainError):
    """Raised when a brief budget cannot deliver content within its cap."""
