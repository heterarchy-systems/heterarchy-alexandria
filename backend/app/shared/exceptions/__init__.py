"""Shared backend exception catalog."""

from .common_exceptions import (
    BoundaryValidationError,
    RedisExceptionAction,
    RedisExceptionArgValue,
    RedisExceptionAware,
    RedisExceptionDecorator,
    RedisExceptionHandler,
    RedisExceptionKwargs,
    RedisExceptionPayload,
    RedisExceptionPolicy,
    RedisExceptionPolicyMap,
    RedisExceptionRawData,
    RedisExceptionResult,
)
from .connections_exceptions import (
    ConnectionsDomainError,
    ConnectionsProviderUnsupportedError,
    ConnectionsResourceNotFoundError,
)
from .exception_decorators import router_exception_status
from .memory_compact_exceptions import (
    MemoryCompactDomainError,
    MemoryCompactNotFoundError,
    MemoryCompactValidationError,
)
from .memory_context_exceptions import (
    MemoryContextDomainError,
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from .obsidian_exceptions import (
    ObsidianDomainError,
    ObsidianGraphUnavailableError,
    ObsidianIndexWriteError,
    ObsidianNotFoundError,
    ObsidianStoredProjectionError,
    ObsidianValidationError,
)
from .route_exceptions import (
    CONNECTIONS_PROVIDER_TEST_EXCEPTION_MAPPING,
    CONNECTIONS_ROUTE_EXCEPTION_MAPPING,
    CONTEXT_ROUTE_EXCEPTION_MAPPING,
    MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING,
    OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
)

__all__ = [
    "CONNECTIONS_PROVIDER_TEST_EXCEPTION_MAPPING",
    "CONNECTIONS_ROUTE_EXCEPTION_MAPPING",
    "CONTEXT_ROUTE_EXCEPTION_MAPPING",
    "MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING",
    "OBSIDIAN_ROUTE_EXCEPTION_MAPPING",
    "BoundaryValidationError",
    "ConnectionsDomainError",
    "ConnectionsProviderUnsupportedError",
    "ConnectionsResourceNotFoundError",
    "MemoryCompactDomainError",
    "MemoryCompactNotFoundError",
    "MemoryCompactValidationError",
    "MemoryContextDomainError",
    "MemoryContextNotFoundError",
    "MemoryContextValidationError",
    "ObsidianDomainError",
    "ObsidianGraphUnavailableError",
    "ObsidianIndexWriteError",
    "ObsidianNotFoundError",
    "ObsidianStoredProjectionError",
    "ObsidianValidationError",
    "RedisExceptionAction",
    "RedisExceptionArgValue",
    "RedisExceptionAware",
    "RedisExceptionDecorator",
    "RedisExceptionHandler",
    "RedisExceptionKwargs",
    "RedisExceptionPayload",
    "RedisExceptionPolicy",
    "RedisExceptionPolicyMap",
    "RedisExceptionRawData",
    "RedisExceptionResult",
    "router_exception_status",
]
