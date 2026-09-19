"""Shared exceptions for Memory Compact bounded-context use cases."""

from __future__ import annotations


class MemoryCompactDomainError(RuntimeError):
    """Base Memory Compact domain exception."""


class MemoryCompactNotFoundError(MemoryCompactDomainError):
    """Raised when a Memory Compact artifact cannot be located."""


class MemoryCompactValidationError(MemoryCompactDomainError):
    """Raised when a Memory Compact invariant is violated."""


class MemoryResumePackageValidationError(MemoryCompactValidationError):
    """Raised when a resume package draft or artifact violates its contract."""


class MemoryResumePackageEvidenceNotFoundError(MemoryResumePackageValidationError):
    """Raised when a resume package references a Context that is not stored."""


class MemoryResumePackageRequestConflictError(MemoryResumePackageValidationError):
    """Raised when a sealed request id is retried with different content."""
