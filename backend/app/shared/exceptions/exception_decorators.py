from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Protocol, cast, runtime_checkable

from app.shared.exceptions.common_exceptions import (
    RedisExceptionArgValue,
    RedisExceptionAware,
    RedisExceptionDecorator,
    RedisExceptionHandler,
    RedisExceptionKwargs,
    RedisExceptionPayload,
    RedisExceptionPolicy,
    RedisExceptionPolicyMap,
    RedisExceptionResult,
)
from fastapi import HTTPException

type RouteExceptionStatusValue = int | tuple[int, str]
type RouteExceptionStatusMapping = Mapping[type[Exception], RouteExceptionStatusValue]
# Broad type justified: FastAPI route handlers may return many response shapes.
type RouteHandlerResult = object
# Broad type justified: route decorators wrap many FastAPI handler signatures.
type RouteAsyncHandler = Callable[..., Awaitable[RouteHandlerResult]]
type RouteExceptionDecorator = Callable[[RouteAsyncHandler], RouteAsyncHandler]


@runtime_checkable
class RouteExceptionWithDetail(Protocol):
    """Exception that exposes a structured route-safe detail payload."""

    # Broad type justified: FastAPI HTTPException detail accepts multiple JSON-compatible shapes.
    def route_detail(self) -> object:
        """Return content suitable for FastAPI's HTTPException detail.

        Returns:
            Result produced by route_detail.
        """


def _resolve_redis_exception_policy(
    error: Exception,
    mapping: RedisExceptionPolicyMap,
) -> RedisExceptionPolicy:
    for exception_type, policy in mapping.items():
        if isinstance(error, exception_type):
            return policy
    raise error


def redis_exceptions(
    mapping: RedisExceptionPolicyMap,
    default_return: RedisExceptionResult = None,
) -> RedisExceptionDecorator:
    """Map shared stream exceptions to retry/drop handling.

    Args:
        mapping: 예외 타입별 스트림 처리 정책.
        default_return: 예외를 정책 처리한 뒤 반환할 기본값.

    Returns:
        공통 Redis 예외 정책을 적용한 비동기 데코레이터.
    """

    def decorator(func: RedisExceptionHandler) -> RedisExceptionHandler:
        @wraps(func)
        async def wrapper(
            self: RedisExceptionAware,
            *args: RedisExceptionArgValue,
            **kwargs: RedisExceptionArgValue,
        ) -> RedisExceptionResult:
            try:
                return await func(self, *args, **kwargs)
            except Exception as error:
                policy = _resolve_redis_exception_policy(
                    error=error,
                    mapping=mapping,
                )
                payload_kwargs = cast(RedisExceptionKwargs, kwargs)
                message_id = cast(
                    str,
                    payload_kwargs.get("message_id", args[0] if args else ""),
                )
                payload = cast(
                    RedisExceptionPayload | None,
                    payload_kwargs.get("payload"),
                )
                retry_count = int(
                    cast(
                        int | str | bytes | None,
                        payload_kwargs.get("retry_count", 0),
                    )
                    or 0
                )
                await self._apply_redis_exception_policy(
                    error=error,
                    policy=policy,
                    message_id=message_id,
                    payload=payload,
                    retry_count=retry_count,
                )
                return default_return

        return wrapper

    return decorator


def router_exception_status(
    mapping: RouteExceptionStatusMapping,
) -> RouteExceptionDecorator:
    """Map route-layer exceptions to HTTP status responses.

    Args:
        mapping [RouteExceptionStatusMapping]: Value supplied to router_exception_status.

    Returns:
        RouteExceptionDecorator: Value produced by router_exception_status.
    """

    def decorator(handler: RouteAsyncHandler) -> RouteAsyncHandler:
        @wraps(handler)
        # Broad type justified: FastAPI route decorators must forward arbitrary handler arguments.
        async def wrapped(*args: object, **kwargs: object) -> RouteHandlerResult:
            try:
                return await handler(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                for exception_type, target in mapping.items():
                    if isinstance(exc, exception_type):
                        if isinstance(target, tuple):
                            status_code, detail = target
                        else:
                            status_code = target
                            detail = (
                                exc.route_detail()
                                if isinstance(exc, RouteExceptionWithDetail)
                                else str(exc) or exception_type.__name__
                            )
                        raise HTTPException(
                            status_code=status_code, detail=detail
                        ) from exc
                raise

        return wrapped

    return decorator
