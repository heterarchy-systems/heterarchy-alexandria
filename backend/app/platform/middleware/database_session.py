"""Request-scoped SQLAlchemy session middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import FastAPI
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.shared.infrastructure.database import Database

DatabaseResolver = Callable[[], Awaitable[Database]]
_TRANSACTION_STATE_SCOPE_KEY = "alexandria.database_transaction_state"


@dataclass(frozen=True, slots=True)
class _DatabaseTransactionState:
    """Typed request-local transaction ownership state."""

    mode: Literal["independent", "read_only"]


def mark_database_transaction_independent(request: Request) -> None:
    """Mark a request whose handler owns all database transaction boundaries.

    Args:
        request: Incoming request whose handler manages independent transactions.
    """
    request.scope[_TRANSACTION_STATE_SCOPE_KEY] = _DatabaseTransactionState(
        mode="independent"
    )


def mark_database_transaction_read_only(request: Request) -> None:
    """Keep a source-read response independent of failed projection transactions.

    This route contract discards all SQL changes at request completion. Canonical
    mutation handlers must keep the normal commit contract instead.

    Args:
        request: Read-only request whose projection session must be rolled back.
    """
    request.scope[_TRANSACTION_STATE_SCOPE_KEY] = _DatabaseTransactionState(
        mode="read_only"
    )


def _database_transaction_is_independent(request: Request) -> bool:
    """Execute database transaction is independent.

    Args:
        request: Validated request for this operation.

    Returns:
        Whether database transaction is independent.
    """
    state = request.scope.get(_TRANSACTION_STATE_SCOPE_KEY)
    return isinstance(state, _DatabaseTransactionState) and state.mode == "independent"


def install_database_session_middleware(
    app: FastAPI,
    resolve_database: DatabaseResolver,
) -> None:
    """Install request-scoped SQLAlchemy session management.

    Args:
        app: FastAPI application receiving the middleware.
        resolve_database: Async callable returning the application database resource.

    Returns:
        None.
    """

    @app.middleware("http")
    async def database_session_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Bind one database session to the current request context.

        Args:
            request: Incoming ASGI request.
            call_next: Next request handler in the middleware chain.

        Returns:
            Response produced by the downstream handler.
        """
        database = await resolve_database()
        async with database.request_session() as session:
            try:
                response = await call_next(request)
            except Exception:
                if not _database_transaction_is_independent(request):
                    await session.rollback()
                raise

            if _database_transaction_is_independent(request):
                return response
            transaction_state = request.scope.get(_TRANSACTION_STATE_SCOPE_KEY)
            read_only = (
                isinstance(transaction_state, _DatabaseTransactionState)
                and transaction_state.mode == "read_only"
            )
            if response.status_code < 400 and not read_only:
                await session.commit()
            else:
                await session.rollback()
            return response
