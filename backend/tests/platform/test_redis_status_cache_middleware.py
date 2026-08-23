"""Short-lived Redis graph and embedding status cache contracts."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.platform.config.redis_config import RedisConfig
from app.platform.middleware.redis_status_cache import RedisStatusCacheMiddleware


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.set_ttls: dict[str, int] = {}
        self.deleted: list[str] = []
        self.closed = 0

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def set(self, key: str, value: bytes, *, ex: int) -> bool:
        self.values[key] = value
        self.set_ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    async def aclose(self) -> None:
        self.closed += 1


def test_graph_and_embedding_status_use_requested_ttls() -> None:
    """Only exact status GETs should be cached for five and ten seconds."""
    fake = _FakeRedis()

    async def resolve_redis_client() -> Redis | None:
        return cast(Redis, fake)

    app = FastAPI()
    app.add_middleware(
        RedisStatusCacheMiddleware,
        config=RedisConfig(
            _env_file=None,
            url="redis://redis:6379/0",
            graph_status_ttl_seconds=5,
            embedding_health_ttl_seconds=10,
        ),
        resolve_redis_client=resolve_redis_client,
    )
    calls = {"graph": 0, "embedding": 0}

    @app.get("/obsidian/graph/projection/status")
    async def graph_status() -> dict[str, int]:
        calls["graph"] += 1
        return {"calls": calls["graph"]}

    @app.get("/memory/contexts/rag/status")
    async def embedding_status(response: Response) -> dict[str, int]:
        response.headers["X-Alexandria-Retrieval-Kernel-Authority"] = "rust"
        calls["embedding"] += 1
        return {"calls": calls["embedding"]}

    with TestClient(app) as client:
        first_graph = client.get("/obsidian/graph/projection/status")
        second_graph = client.get("/obsidian/graph/projection/status")
        first_embedding = client.get("/memory/contexts/rag/status")
        second_embedding = client.get("/memory/contexts/rag/status")

    assert first_graph.headers["X-Alexandria-Cache"] == "MISS"
    assert second_graph.headers["X-Alexandria-Cache"] == "HIT"
    assert first_embedding.headers["X-Alexandria-Cache"] == "MISS"
    assert second_embedding.headers["X-Alexandria-Cache"] == "HIT"
    assert first_embedding.headers["X-Alexandria-Retrieval-Kernel-Authority"] == "rust"
    assert second_embedding.headers["X-Alexandria-Retrieval-Kernel-Authority"] == "rust"
    assert calls == {"graph": 1, "embedding": 1}
    assert fake.set_ttls["alexandria:cache:graph-status:v1"] == 5
    assert fake.set_ttls["alexandria:cache:graph-status:v1:headers"] == 5
    assert fake.set_ttls["alexandria:cache:embedding-health:v1"] == 10
    assert fake.set_ttls["alexandria:cache:embedding-health:v1:headers"] == 10
    assert fake.closed == 0


def test_related_mutations_invalidate_cached_status() -> None:
    """Successful maintenance mutations should evict affected short TTL entries."""
    fake = _FakeRedis()
    fake.values = {
        "alexandria:cache:graph-status:v1": b"{}",
        "alexandria:cache:graph-status:v1:headers": b"{}",
        "alexandria:cache:embedding-health:v1": b"{}",
        "alexandria:cache:embedding-health:v1:headers": b"{}",
    }

    async def resolve_redis_client() -> Redis | None:
        return cast(Redis, fake)

    app = FastAPI()
    app.add_middleware(
        RedisStatusCacheMiddleware,
        config=RedisConfig(_env_file=None, url="redis://redis:6379/0"),
        resolve_redis_client=resolve_redis_client,
    )

    @app.post("/obsidian/index/rebuild")
    async def rebuild_index() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.post("/obsidian/index/rebuild")

    assert response.status_code == 200
    assert set(fake.deleted) == {
        "alexandria:cache:graph-status:v1",
        "alexandria:cache:graph-status:v1:headers",
        "alexandria:cache:embedding-health:v1",
        "alexandria:cache:embedding-health:v1:headers",
    }
    assert fake.values == {}
