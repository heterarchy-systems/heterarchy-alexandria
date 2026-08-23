# Backend AGENTS.md

## Scope

이 문서는 `backend/` 디렉터리와 그 하위 전체에 적용됩니다.

## Mandatory rule sources

Backend 코드를 수정하기 전에는 다음 문서를 순서대로 읽습니다.

1. `.agents/python_dev_harness/docs/rule/규칙.md`
2. `.agents/python_dev_harness/docs/rule/README.md`
3. `README.md`에서 현재 작업과 직접 관련된 세부 규칙
4. 사용자가 명시적으로 지정한 PRD 또는 작업 문서
5. 관련 코드와 테스트

Backend 개발 규칙의 Source of Truth는 다음 디렉터리입니다.

```text
.agents/python_dev_harness/docs/rule/
```

PRD, 회의록, 기능 요구사항은 개발 규칙이 아닙니다. 사용자가 명시적으로 지정하거나 저장소에서 현재 Task에 연결한 경우에만 작업 입력으로 사용합니다.

## Rules

- 기존 구조를 먼저 조사하고 재사용합니다.
- 내부 object DTO는 dataclass, 외부 I/O DTO는 Pydantic v2 schema, dictionary payload contract는 TypedDict를 기본값으로 사용합니다.
- Obsidian Markdown은 Canonical Storage이며 PostgreSQL의 FTS/pgvector/Embedding 파생 상태와 Neo4j Graph Projection은 재구축 가능한 Index 또는 Read Model입니다. Runtime persistence는 PostgreSQL만 허용하며 SQLite compatibility/fallback은 금지합니다.
- 새로운 Backend 패턴을 도입하기 전에 규칙과 기존 구현의 충돌 여부를 확인합니다.
- 규칙과 실제 구현이 어긋나면 임의로 우회하지 않고 Source of Truth를 먼저 정리합니다.
- 상위 시스템, 개발자, 사용자 지시가 있으면 해당 지시가 우선합니다.



## Subagent Routing Policy

The primary agent owns:

- requirements
- architecture
- task decomposition
- conflict resolution
- final diff review
- final verification
- completion claims

Use `luna_feature_auditor` when:

- one bounded feature or persistence path needs deep inspection
- contracts must be compared across layers
- invariants or missing tests must be identified

Use `luna_test_analyst` when:

- a bounded test suite, migration, or runtime execution fails
- the root cause is not yet proven

Use `luna_bounded_worker` only when all of the following are frozen:

- exact behavior
- allowed files
- acceptance criteria
- tests to run
- explicitly excluded scope

Use `terra_integration_reviewer` after implementation and before
the primary agent declares completion.

Execution constraints:

1. Prefer read-only parallelism.
2. Run at most three read-only agents concurrently.
3. Run at most one workspace-write agent at a time.
4. Never allow two agents to edit overlapping files.
5. Wait for all requested read-only agents before freezing implementation scope.
6. Reconcile conflicting findings in the primary thread.
7. The primary agent must inspect the final diff.
8. The primary agent must run the full relevant verification suite.
9. Subagent completion is not project completion.
10. Preserve all pre-existing dirty and uncommitted work.