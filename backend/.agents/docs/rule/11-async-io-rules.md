# Async and I/O Rules

## 기본 원칙

순수 Validation, Mapping, Hash, Normalization은 동기 함수로 유지한다. 실제 외부 대기가 있는 경계에만 Async를 사용한다.

좋은 Async 대상:

- HTTP Client
- MCP Remote Call
- Subprocess
- Stream Ingestion
- 비동기 Database Driver
- 외부 File Watcher

동기로 유지할 대상:

- Pydantic Validation
- Dataclass Construction
- Frontmatter Mapping
- Scope Validation
- Search Result Filtering
- Hash Calculation
- Lifecycle Decision

## Blocking I/O

Async Endpoint와 MCP Handler에서 Blocking I/O를 event-loop thread에서 직접 실행하지 않는다.

우선순위는 다음과 같다.

1. async-native library/adapter를 사용한다.
2. 피할 수 없는 동기 SDK 또는 파일 경계는 repository 표준 `asyncer.asyncify` wrapper로 한 곳에서 감싼다.
3. Production code에서 `asyncio.to_thread`를 직접 사용하지 않는다.

Blocking boundary는 호출 지점 전체에 흩뿌리지 않고 adapter/provider 경계에 국한한다.

## Task Group과 동시성

실제 독립적인 Concurrent I/O에만 Task Group을 사용한다. 순차 Validation이나 Schema Construction을 병렬화하지 않는다.

사용자 입력 크기에 비례하는 unbounded `asyncio.gather()`를 금지한다. 동시성은 명시적 상한, semaphore, worker pool 또는 외부 queue 정책으로 제한한다.

## Database Session

하나의 `AsyncSession`을 동시에 실행되는 task들 사이에서 공유하지 않는다. Engine/pool은 application lifetime resource지만 Session/transaction은 request 또는 use-case lifetime이다.

## Lifespan

FastAPI, MCP ASGI app, PostgreSQL/Redis/Neo4j/provider client처럼 startup/shutdown이 필요한 resource는 lifespan 또는 DI `providers.Resource`를 통해 deterministic하게 소유한다.

Import 시점에 remote I/O, pool 생성, background task 시작을 수행하지 않는다.

## Local Import

순환 의존을 피하기 위한 일반 전략으로 Local Import를 사용하지 않는다. 책임 경계를 먼저 분리한다. 외부 Runtime Boundary에서 정말 피할 수 없을 때만 이유를 기록한다.

## Verification

Mechanical async verifier는 production의 직접 `asyncio.to_thread`, 금지된 import-time side effect 패턴, 명백한 blocking boundary 위반을 fail-closed로 검사한다. 예외 baseline을 유지하지 않는다.
