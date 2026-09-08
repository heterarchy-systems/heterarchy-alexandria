"""Stable failures for aggregate memory-cycle fencing and recovery."""

from __future__ import annotations


class MemoryCycleDomainError(RuntimeError):
    """Base aggregate memory-cycle exception."""


class MemoryCycleValidationError(MemoryCycleDomainError):
    """Raised when a cycle request violates its bounded contract."""


class MemoryCycleStalePlanError(MemoryCycleDomainError):
    """Raised when canonical source or compact state changed after planning."""


class MemoryCycleRecoveryRequiredError(MemoryCycleDomainError):
    """Raised when a durable checkpoint cannot be verified for safe replay."""
