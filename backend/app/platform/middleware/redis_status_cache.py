"""Fail-open Redis response cache for short-lived status endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Protocol, cast

from fastapi import FastAPI
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.platform.config.redis_config import RedisConfig
from app.shared.serialization.orjson_codec import dumps_json, loads_json
from app.shared.types.extra_types import JSONValue

RequestHandler = Callable[[Request], Awaitable[Response]]
RedisClientResolver = Callable[[], Awaitable[Redis | None]]

_GRAPH_STATUS_PATH = "/obsidian/graph/projection/status"
_EMBEDDING_HEALTH_PATH = "/memory/contexts/rag/status"
_GRAPH_CACHE_KEY = "alexandria:cache:graph-status:v1"
_EMBEDDING_CACHE_KEY = "alexandria:cache:embedding-health:v1"
_INVALIDATION_PATHS = {
    "/obsidian/graph/projection/rebuild": (_GRAPH_CACHE_KEY,),
    "/obsidian/index/rebuild": (_GRAPH_CACHE_KEY, _EMBEDDING_CACHE_KEY),
    "/memory/contexts/retrieval/soft-rebuild": (_EMBEDDING_CACHE_KEY,),
    "/operations/maintenance/embedding-reindex/jobs": (_EMBEDDING_CACHE_KEY,),
}


# protocol-contract: structural-seam
class ResponseBodyStream(Protocol):
    """Narrow Starlette streaming response surface returned by call_next."""

    body_iterator: AsyncIterator[bytes]


class RedisStatusCacheMiddleware(BaseHTTPMiddleware):
    """Cache only graph status and embedding health for bounded TTLs."""

    def __init__(
        self,
        app: ASGIApp,
        config: RedisConfig,
        resolve_redis_client: RedisClientResolver,
    ) -> None:
        """Initialize RedisStatusCacheMiddleware state and dependencies.

        Args:
            app: App used by this operation.
            config: Typed configuration used by this operation.
            resolve_redis_client: Resolve redis client used by this operation.
        """
        super().__init__(app)
        self._enabled = config.url is not None
        self._resolve_redis_client = resolve_redis_client
        self._policies = {
            _GRAPH_STATUS_PATH: (
                _GRAPH_CACHE_KEY,
                config.graph_status_ttl_seconds,
            ),
            _EMBEDDING_HEALTH_PATH: (
                _EMBEDDING_CACHE_KEY,
                config.embedding_health_ttl_seconds,
            ),
        }

    async def dispatch(
        self,
        request: Request,
        call_next: RequestHandler,
    ) -> Response:
        """Serve exact GET cache hits and invalidate related successful writes.

        Args:
            request: Incoming Starlette request.
            call_next: Next request handler in the middleware chain.

        Returns:
            Cached, rebuilt, or uncached HTTP response.
        """
        if not self._enabled:
            return await call_next(request)
        client = await self._resolve_redis_client()
        if client is None:
            return await call_next(request)
        policy = self._policies.get(request.url.path)
        if request.method == "GET" and policy is not None:
            return await self._cached_response(
                client,
                request,
                call_next,
                policy[0],
                policy[1],
            )
        response = await call_next(request)
        invalidation_keys = _INVALIDATION_PATHS.get(request.url.path, ())
        if invalidation_keys and response.status_code < 400:
            await _delete_fail_open(client, _expanded_cache_keys(invalidation_keys))
        return response

    async def _cached_response(
        self,
        client: Redis,
        request: Request,
        call_next: RequestHandler,
        cache_key: str,
        ttl_seconds: int,
    ) -> Response:
        """Execute cached response.

        Args:
            client: Client used by this operation.
            request: Validated request for this operation.
            call_next: Call next used by this operation.
            cache_key: Cache key used by this operation.
            ttl_seconds: Ttl seconds used by this operation.

        Returns:
            Response result produced by cached response.
        """
        cached = await _get_fail_open(client, cache_key)
        cached_headers = await _get_fail_open(client, _headers_cache_key(cache_key))
        decoded_headers = (
            None if cached_headers is None else _decode_response_headers(cached_headers)
        )
        if cached is not None and decoded_headers is not None:
            decoded_headers["X-Alexandria-Cache"] = "HIT"
            return Response(
                content=cached,
                status_code=200,
                headers=decoded_headers,
            )
        response = await call_next(request)
        stream = cast(ResponseBodyStream, response)
        body = await _response_body(stream.body_iterator)
        headers = dict(response.headers)
        cache_headers = dict(response.headers)
        headers["X-Alexandria-Cache"] = "MISS"
        rebuilt = Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )
        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and content_type.startswith("application/json"):
            with suppress(RedisError):
                body_operation = client.set(cache_key, body, ex=ttl_seconds)
                await cast(Awaitable[bool | None], body_operation)
                headers_operation = client.set(
                    _headers_cache_key(cache_key),
                    _encode_response_headers(cache_headers),
                    ex=ttl_seconds,
                )
                await cast(Awaitable[bool | None], headers_operation)
        return rebuilt


def install_redis_status_cache_middleware(
    app: FastAPI,
    config: RedisConfig,
    resolve_redis_client: RedisClientResolver,
) -> None:
    """Install exact-path short-lived status caching.

    Args:
        app: FastAPI application receiving the middleware.
        config: Validated optional Redis cache settings.
        resolve_redis_client: Async resolver for the lifecycle-owned Redis client.
    """
    app.add_middleware(
        RedisStatusCacheMiddleware,
        config=config,
        resolve_redis_client=resolve_redis_client,
    )


async def _get_fail_open(client: Redis, key: str) -> bytes | None:
    """Return fail open.

    Args:
        client: Client used by this operation.
        key: Key used by this operation.

    Returns:
        Requested fail open.
    """
    try:
        operation = client.get(key)
        value = await cast(Awaitable[bytes | str | None], operation)
    except RedisError:
        return None
    if isinstance(value, bytes):
        return value
    return None


def _headers_cache_key(cache_key: str) -> str:
    """Return the companion key for cached response-header metadata.

    Args:
        cache_key: Redis key storing the cached response body.

    Returns:
        Redis key storing the matching response headers.
    """
    return f"{cache_key}:headers"


def _expanded_cache_keys(cache_keys: tuple[str, ...]) -> tuple[str, ...]:
    """Return body and header keys for cache invalidation.

    Args:
        cache_keys: Status-response body cache keys to invalidate.

    Returns:
        Body keys interleaved with their companion header keys.
    """
    return tuple(
        key
        for cache_key in cache_keys
        for key in (cache_key, _headers_cache_key(cache_key))
    )


def _encode_response_headers(headers: dict[str, str]) -> bytes:
    """Serialize response headers for a short-lived status cache entry.

    Args:
        headers: Original response headers emitted before cache decoration.

    Returns:
        JSON bytes containing the response-header snapshot.
    """
    return dumps_json(cast(JSONValue, headers))


def _decode_response_headers(value: bytes) -> dict[str, str] | None:
    """Validate and decode cached response-header metadata.

    Args:
        value: Serialized response-header metadata read from Redis.

    Returns:
        Validated response headers, or None for malformed or legacy metadata.
    """
    try:
        decoded = loads_json(value)
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    headers: dict[str, str] = {}
    for name, header_value in decoded.items():
        if not isinstance(header_value, str):
            return None
        headers[name] = header_value
    return headers


async def _delete_fail_open(client: Redis, keys: tuple[str, ...]) -> None:
    """Delete fail open.

    Args:
        client: Client used by this operation.
        keys: Keys used by this operation.
    """
    try:
        operation = client.delete(*keys)
        await cast(Awaitable[int], operation)
    except RedisError:
        return


async def _response_body(iterator: AsyncIterator[bytes]) -> bytes:
    """Execute response body.

    Args:
        iterator: Iterator used by this operation.

    Returns:
        bytes result produced by response body.
    """
    body = bytearray()
    async for chunk in iterator:
        body.extend(chunk)
    return bytes(body)
