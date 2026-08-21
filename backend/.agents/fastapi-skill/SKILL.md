---
name: fastapi-production-backend
description: Production FastAPI architecture, lifespan/resource ownership, strict Pydantic v2 boundaries, routing, testing, performance, and HTTP/MCP integration guidance for heterarchy-alexandria.
argument-hint: "[backend boundary or use case]"
license: MIT
metadata:
  author: heterarchy-systems
  version: "1.0.0"
  researched_at: "2026-08-19"
---

# FastAPI Production Backend Skill

## Authority

This skill is reusable methodology adapted from the live `heterarchy-orchestration` repository. Repository-local rules under `backend/.agents/docs/rule/` are mandatory and win on conflict.

Primary source set retained from the live skill:

- FastAPI: Bigger Applications / Multiple Files
- FastAPI: Dependencies and `Annotated`
- FastAPI: Lifespan Events
- FastAPI: Response Model / Return Type
- FastAPI: Return a Response Directly
- Dependency Injector FastAPI examples where framework integration matters

## Architecture

Use a thin-interface architecture:

```text
FastAPI / MCP transport
  -> Pydantic boundary validation
  -> application service / coordinator
  -> repository ports
  -> infrastructure adapters / ORM / Obsidian adapters
```

Path operations validate, authorize, map, and delegate. They do not duplicate lifecycle policy, storage authority, transaction policy, or recovery algorithms.

Split routers by bounded context and compose them in an application factory. Importing a module must not open database pools, start workers, or perform remote I/O.

## Lifespan and Resources

Use ASGI lifespan for application-scoped resources requiring deterministic startup/shutdown:

- SQLAlchemy async engine and pool
- Redis clients / stream resources
- Neo4j driver used for rebuildable graph projection
- async HTTP/provider clients
- Dependency Injector resources
- MCP ASGI lifespan when mounted with FastAPI

Never create an engine/pool per request and never share a request-scoped `AsyncSession` as global mutable state.

## Dependency Boundaries

FastAPI dependencies own request extraction, authentication, protocol context, and request-scoped glue. Dependency Injector owns application object assembly.

When `dependency-injector` is used:

- object graph assembly belongs to the container;
- FastAPI `Depends` bridges routes to `Provide[...]`;
- application/domain services never call the container as a service locator;
- `@inject` stays immediately above the function and below the route decorator.

Prefer `Annotated[T, Depends(...)]` for boundary dependencies.

## Async Rules

Use `async def` only where async I/O is awaited. Keep validation, mapping, hashing, normalization, and pure schema construction synchronous.

Blocking work must not run on the event-loop thread. Prefer an async-native adapter; otherwise use the repository-standard `asyncer.asyncify` boundary. Production `asyncio.to_thread` is not the standard modernization path.

Do not use unbounded concurrency over user-controlled collections.

## Strict Pydantic v2 Boundaries

All named-field schemas inherit `StrictSchemaModel`; root-value schemas inherit `StrictRootSchemaModel`. Do not subclass Pydantic `BaseModel` / `RootModel` directly outside the canonical shared schema module.

Canonical configuration is strict and immutable:

- `extra="forbid"` for named models;
- `frozen=True`;
- `strict=True`;
- `use_enum_values=True`;
- `validate_default=True`.

Externally visible fields carry meaningful descriptions through the repository `described_field()` helper. Production schema modules do not call `pydantic.Field()` directly. Actual defaults remain annotation assignments rather than helper defaults/default factories.

String constraints use `Annotated[str, StringConstraints(strict=True, ...)]` where constraints are needed.

FastAPI pre-decodes JSON into Python values, which can break strict JSON semantics for enum/UUID/datetime boundaries. Such request bodies must use one shared dependency that reads the raw request body and calls `model_validate_json()`. Do not weaken `strict=True` to work around FastAPI predecode behavior.

Top-level API/MCP collection contracts use named root schemas instead of anonymous bare collections.

## Responses

Prefer typed Pydantic response models. Map ORM/read models explicitly rather than relying on accidental coercion or dumping `__dict__`.

Do not manually construct `JSONResponse` or revive deprecated ORJSON response defaults for ordinary application JSON. A direct `Response` is reserved for protocol seams that intentionally bypass normal FastAPI conversion, and its payload should still come from a typed schema serializer.

## Database Request Lifecycle

Recommended ownership:

- Engine/pool: application lifespan.
- Session: request/use-case scope.
- Transaction: application service/unit-of-work boundary.
- ORM model: infrastructure layer.
- Domain DTO/entity: framework-independent layer.

Do not share one `AsyncSession` across concurrently executing tasks. Repository methods do not hide transaction ownership unless their contract explicitly owns it.

## Alexandria Authority Boundary

Preserve the storage split:

- Obsidian Markdown is canonical knowledge/source authority.
- PostgreSQL is authoritative for runtime relational state, index metadata, FTS/vector retrieval, OAuth and maintenance records.
- Neo4j is a rebuildable graph projection, not canonical source storage.
- Redis is ephemeral cache/queue/coordination state, never durable knowledge authority.

FastAPI and MCP adapters must not collapse these authorities into a second competing source of truth.

## Testing

Verify layers independently:

1. domain/application unit tests;
2. PostgreSQL repository integration tests;
3. FastAPI ASGI validation/routing/error tests;
4. MCP transport and schema tests;
5. OAuth/integration flows where changed;
6. real cross-resource integration before making a real-integration claim.

Provider/DI overrides may make tests deterministic but may not weaken production contracts.

## Completion Gate

Before reporting a FastAPI slice complete:

- repository rules loaded;
- focused regressions pass;
- Ruff format/lint pass;
- Pyrefly passes;
- relevant PostgreSQL/MCP/OAuth integration passes;
- canonical `make ci` passes;
- no unexecuted E2E is described as PASS.
