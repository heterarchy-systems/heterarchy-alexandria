"""Neo4j graph projection contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Concatenate, ParamSpec, Protocol, TypedDict, TypeVar


class Neo4jProjectionRawRow(TypedDict, total=False):
    """Validated subset of scalar fields returned by projection queries."""

    note_id: str | None
    relative_path: str
    alexandria_type: str
    title: str
    status: str
    project: str | None
    edge_id: str
    source_note_id: str
    source_path: str
    target_note_id: str | None
    target_path: str
    relation: str
    confidence: float
    source_kind: str
    run_id: str | None
    projection_version: int | None
    related_note_id: str
    direction: str
    score: float
    target_title: str
    signal: str
    issue_total: int | None
    issue_counts_json: str | None


class Neo4jProjectionRunParameters(TypedDict):
    """Projection metadata parameters shared across write statements."""

    projection_name: str
    projection_version: int
    run_id: str


class Neo4jProjectionActivationParameters(Neo4jProjectionRunParameters):
    """Projection activation parameters including last-run diagnostics."""

    issue_total: int
    issue_counts_json: str


class Neo4jProjectionNodeParameters(TypedDict):
    """One non-secret node parameter row for an UNWIND batch."""

    projection_key: str
    note_id: str
    relative_path: str
    alexandria_type: str
    title: str
    status: str
    project: str | None


class Neo4jProjectionEdgeParameters(TypedDict):
    """One non-secret relationship parameter row for an UNWIND batch."""

    edge_id: str
    source_key: str
    source_note_id: str
    source_path: str
    target_key: str
    target_note_id: str | None
    target_path: str
    relation: str
    confidence: float
    source_kind: str


PROJECTION_NAME = "obsidian"
_P = ParamSpec("_P")
_R = TypeVar("_R")
Neo4jProjectionParameter = (
    str
    | int
    | float
    | bool
    | None
    | list[Neo4jProjectionNodeParameters]
    | list[Neo4jProjectionEdgeParameters]
    | list[str]
)


# protocol-contract: structural-seam
class Neo4jProjectionResult(Protocol):
    """Narrow async result behavior consumed by this adapter."""

    async def data(self) -> list[Neo4jProjectionRawRow]:
        """Return result records as typed mappings.

        Returns:
            Scalar projection result rows.
        """

    # Broad type justified: the adapter discards the driver's version-specific
    # ResultSummary and only requires completion of result consumption.
    async def consume(self) -> object:
        """Consume the result before another query runs in the transaction.

        Returns:
            Driver-specific summary ignored by this adapter.
        """


# protocol-contract: structural-seam
class Neo4jProjectionTransaction(Protocol):
    """Narrow transaction behavior consumed by transaction callbacks."""

    async def run(
        self,
        query: str,
        **parameters: Neo4jProjectionParameter,
    ) -> Neo4jProjectionResult:
        """Execute one parameterized Cypher statement.

        Args:
            query: Static Cypher template.
            parameters: Non-secret values bound to named Cypher parameters.

        Returns:
            Async query result wrapper.
        """


# protocol-contract: structural-seam
class Neo4jProjectionSession(Protocol):
    """Short-lived async session behavior used by one repository operation."""

    async def __aenter__(self) -> Neo4jProjectionSession:
        """Enter the session context.

        Returns:
            Active operation-local session.
        """

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the session context.

        Args:
            exc_type: Raised exception type, when present.
            exc: Raised exception, when present.
            traceback: Raised exception traceback, when present.
        """

    async def execute_write(
        self,
        callback: Callable[
            Concatenate[Neo4jProjectionTransaction, _P],
            Awaitable[_R],
        ],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        """Execute an idempotent write callback with driver-managed retries.

        Args:
            callback: Retry-safe transaction callback.
            args: Positional callback arguments.
            kwargs: Named callback arguments.

        Returns:
            Callback result.
        """

    async def execute_read(
        self,
        callback: Callable[
            Concatenate[Neo4jProjectionTransaction, _P],
            Awaitable[_R],
        ],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        """Execute a read callback.

        Args:
            callback: Read transaction callback.
            args: Positional callback arguments.
            kwargs: Named callback arguments.

        Returns:
            Callback result.
        """


# protocol-contract: structural-seam
class Neo4jProjectionDriver(Protocol):
    """One application-lifetime async Neo4j driver."""

    def session(self, database: str | None = None) -> Neo4jProjectionSession:
        """Create one operation-local async session.

        Args:
            database: Explicit Neo4j database name.

        Returns:
            New short-lived async session.
        """

    async def close(self) -> None:
        """Close the application-lifetime driver."""

    async def verify_connectivity(self) -> None:
        """Verify connectivity only when explicitly requested."""
