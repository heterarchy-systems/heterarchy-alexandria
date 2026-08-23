"""Shared route exception mapping contracts."""

from __future__ import annotations

from fastapi import status

from app.shared.exceptions.common_exceptions import (
    BoundaryValidationError,
    IndexMaintenanceConflictError,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
    ConnectionsResourceNotFoundError,
)
from app.shared.exceptions.exception_decorators import RouteExceptionStatusMapping
from app.shared.exceptions.librarian_exceptions import (
    LibrarianProviderUnsupportedError,
    LibrarianResourceNotFoundError,
    LibrarianValidationError,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryCompactNotFoundError,
    MemoryCompactValidationError,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianGraphUnavailableError,
    ObsidianIdempotencyConflictError,
    ObsidianIdentityConflictError,
    ObsidianNotFoundError,
    ObsidianValidationError,
    ObsidianWriteConflictError,
    ObsidianWriteTargetNotFoundError,
)

CONNECTIONS_PROVIDER_TEST_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    ConnectionsResourceNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Provider not found",
    ),
}

MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    BoundaryValidationError: status.HTTP_400_BAD_REQUEST,
    MemoryCompactNotFoundError: status.HTTP_404_NOT_FOUND,
    MemoryCompactValidationError: status.HTTP_400_BAD_REQUEST,
}

CONNECTIONS_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    BoundaryValidationError: status.HTTP_400_BAD_REQUEST,
    ConnectionsProviderUnsupportedError: status.HTTP_400_BAD_REQUEST,
    ConnectionsResourceNotFoundError: status.HTTP_404_NOT_FOUND,
}

CONTEXT_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    BoundaryValidationError: status.HTTP_400_BAD_REQUEST,
    MemoryContextNotFoundError: status.HTTP_404_NOT_FOUND,
    MemoryContextValidationError: status.HTTP_400_BAD_REQUEST,
    IndexMaintenanceConflictError: status.HTTP_409_CONFLICT,
}

OBSIDIAN_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    BoundaryValidationError: status.HTTP_400_BAD_REQUEST,
    ObsidianNotFoundError: status.HTTP_404_NOT_FOUND,
    ObsidianValidationError: status.HTTP_400_BAD_REQUEST,
    ObsidianGraphUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    IndexMaintenanceConflictError: status.HTTP_409_CONFLICT,
}

OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    **OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
    ObsidianValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ObsidianWriteConflictError: status.HTTP_409_CONFLICT,
    ObsidianIdentityConflictError: status.HTTP_409_CONFLICT,
    ObsidianIdempotencyConflictError: status.HTTP_409_CONFLICT,
    ObsidianWriteTargetNotFoundError: status.HTTP_404_NOT_FOUND,
}

OPERATIONS_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    BoundaryValidationError: status.HTTP_400_BAD_REQUEST,
}

LIBRARIAN_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    BoundaryValidationError: status.HTTP_400_BAD_REQUEST,
    LibrarianProviderUnsupportedError: status.HTTP_400_BAD_REQUEST,
    LibrarianResourceNotFoundError: status.HTTP_404_NOT_FOUND,
    LibrarianValidationError: status.HTTP_400_BAD_REQUEST,
}
