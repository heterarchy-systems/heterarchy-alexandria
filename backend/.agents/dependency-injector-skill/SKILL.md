---
name: python-dependency-injector-production
description: Production use of python-dependency-injector with FastAPI/MCP, async resources, SQLAlchemy, Redis/Neo4j clients, test overrides, explicit wiring, provider scoping, and clean-architecture boundaries.
argument-hint: "[container, provider, or injection boundary]"
license: MIT
metadata:
  author: heterarchy-systems
  version: "1.0.0"
  researched_at: "2026-08-19"
---

# Python Dependency Injector Production Skill

## Authority

This skill is reusable methodology adapted from the live `heterarchy-orchestration` repository. Repository-local rules under `backend/.agents/docs/rule/` are mandatory and win on conflict.

Primary source set retained from the live skill:

- Dependency Injector FastAPI example
- FastAPI + SQLAlchemy example
- FastAPI + Redis example
- Providers overview
- Factory / Singleton / Resource providers
- ASGI Lifespan support
- Wiring and asynchronous injections
- Provider overriding / testing

## Core Principle

Dependency Injector makes object assembly explicit. The container is the composition root, not a runtime service locator.

```text
Container
  -> validated configuration
  -> shared resources
  -> repository adapters
  -> services/coordinators
  -> FastAPI/MCP boundary injection
```

Business code receives dependencies through constructors/functions and does not import or call the container.

## Declarative Container

Prefer `containers.DeclarativeContainer` for the composition root. Named subcontainers are acceptable for large bounded contexts when ownership stays clear.

Do not split containers simply to mirror every module.

## Provider Selection

### Factory

Use `providers.Factory` for lightweight stateful/use-case objects that should be constructed for an injection/use-case boundary, including repositories bound to a unit of work and application services that should not be global mutable state.

### Singleton

Use `providers.Singleton` only for truly application-scoped, concurrency-safe objects such as immutable configuration adapters or documented thread/async-safe clients.

Never use Singleton for SQLAlchemy `Session` / `AsyncSession` or request-scoped mutable state.

### Resource

Use `providers.Resource` for initialize/yield/shutdown lifecycles:

- SQLAlchemy engine/session-factory owner;
- Redis client/queue resources;
- Neo4j driver;
- async HTTP/provider clients;
- other long-lived clients with deterministic cleanup.

Prefer ASGI lifespan integration so resources start before request handling and close at shutdown.

### Configuration

Use validated Pydantic Settings and/or `providers.Configuration` as the startup configuration boundary. Do not scatter environment parsing through repositories/services.

## FastAPI Integration

Canonical pattern:

```python
@router.get("/items")
@inject
async def list_items(
    service: Annotated[
        ItemService,
        Depends(Provide[ApplicationContainer.item_service]),
    ],
) -> ItemListResponse:
    return await service.list_items()
```

Rules:

- route decorator is outer and `@inject` is immediately above the function;
- prefer `Annotated[T, Depends(Provide[...])]` for endpoint injection;
- wire only packages/modules containing injection markers;
- routes remain thin;
- FastAPI owns request extraction/security/context, while Dependency Injector owns application object assembly.

## MCP Integration

MCP tools/resources/prompts are transport boundaries. Resolve application services through explicit composition/injection rather than importing global container state inside tool handlers.

When the MCP ASGI application and FastAPI both require lifespan, compose lifespan explicitly. Do not assume mounted child lifespan runs automatically.

## Async Resources

Know whether a provider is sync or async and await async-mode providers consistently. Avoid accidental async-mode switching from mixed resource implementations.

Do not hide blocking I/O behind an async provider. Use async-native resources or the repository-standard explicit async boundary.

## SQLAlchemy Ownership

Recommended graph:

```text
Resource: AsyncEngine / sessionmaker owner
     ↓
request/use-case session
     ↓
Factory: Repository(session)
     ↓
Factory: Service(repository)
```

The engine/pool is application scoped. `AsyncSession` is unit-of-work/request scoped and must not be shared across concurrent tasks.

Repositories receive persistence dependencies; they do not create engines or read environment variables. Commit/rollback ownership must be explicit at the application/unit-of-work boundary.

## Redis and Neo4j Ownership

Redis and Neo4j clients may be application-scoped resources when their client libraries support safe sharing, but their semantic authority remains separate:

- Redis is ephemeral cache/queue coordination;
- Neo4j is rebuildable projection;
- neither becomes a durable knowledge source by virtue of being application-scoped.

## Wiring Discipline

Use `wiring_config` or explicit `container.wire(...)` deliberately.

Avoid:

- wiring the entire source tree by default;
- `Provide[...]` markers in domain entities;
- importing `ApplicationContainer` inside application/domain services;
- runtime `container.service()` calls from business logic;
- circular provider graphs.

## Provider Overrides in Tests

Use provider override contexts for deterministic composition. Overrides replace dependencies; they do not justify production `if testing:` branches.

Reset resource/singleton state between tests when isolation requires it.

## Scope and State Rules

- Container owns assembly, not business state.
- Repository owns persistence interaction.
- Service owns use-case invariants.
- Coordinator owns cross-service policy.
- FastAPI/MCP handler owns transport validation/delegation.
- Obsidian/PostgreSQL/Neo4j/Redis authority semantics are not duplicated inside DI state.

## Performance

Resolve services at request/tool entry rather than repeatedly inside hot loops. Keep expensive safe clients application scoped, sessions narrowly scoped, and avoid needless wrapper providers around pure functions.

## Completion Gate

Before reporting DI work complete:

- container creation performs no import-time network/DB side effects;
- resource startup/shutdown is deterministic and tested;
- endpoint/tool injection is wired and type-checked;
- external dependencies can be overridden in tests;
- no service-locator calls remain in application/domain code;
- focused tests pass;
- canonical `make ci` passes.
