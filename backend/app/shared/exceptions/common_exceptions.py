from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Literal


class BoundaryValidationError(RuntimeError):
    """Raised when a shared boundary contract value is invalid."""


class IndexMaintenanceConflictError(RuntimeError):
    """Raised when another expensive index maintenance operation is active."""


type RedisExceptionAction = Literal["drop", "retry"]
type RedisJSONValue = (
    str
    | int
    | float
    | bool
    | None
    | list["RedisJSONValue"]
    | dict[str, "RedisJSONValue"]
)
type RedisExceptionPayload = dict[str, RedisJSONValue]
type RedisExceptionRawData = dict[str, str | bytes]
type RedisExceptionArgValue = (
    RedisExceptionPayload
    | RedisExceptionRawData
    | dict[str, str]
    | str
    | bytes
    | int
    | None
)
type RedisExceptionKwargs = dict[str, RedisExceptionArgValue]
type RedisExceptionResult = RedisExceptionPayload | None


@dataclass(frozen=True, slots=True)
class RedisExceptionPolicy:
    """Redis exception handling policy metadata."""

    action: RedisExceptionAction
    log_level: int
    message_template: str


type RedisExceptionPolicyMap = dict[type[Exception], RedisExceptionPolicy]


class RedisExceptionAware(ABC):
    """Context contract required by the redis exception decorator."""

    _logger: Logger

    @abstractmethod
    async def _apply_redis_exception_policy(
        self,
        error: Exception,
        policy: RedisExceptionPolicy,
        message_id: str,
        payload: RedisExceptionPayload | None,
        retry_count: int,
    ) -> None:
        """Handle one mapped exception according to the stream policy.

        Args:
            error: Error value being processed.
            policy: Policy used by this operation.
            message_id: Identifier for message.
            payload: Validated payload for this operation.
            retry_count: Retry count used by this operation.
        """


type RedisExceptionHandler = Callable[..., Awaitable[RedisExceptionResult]]
type RedisExceptionDecorator = Callable[[RedisExceptionHandler], RedisExceptionHandler]

__all__ = [
    "BoundaryValidationError",
    "IndexMaintenanceConflictError",
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
]
