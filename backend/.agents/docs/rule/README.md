# heterarchy-alexandria Rules Index

이 디렉터리는 heterarchy-alexandria 전용 개발 규칙의 Source of Truth다.

## 문서

1. `규칙.md`
   - 모든 작업에 적용하는 최상위 규칙
2. `00-overview.md`
   - 하네스 목적과 기본 철학
3. `01-architecture-boundary-rules.md`
   - API, Service, Repository, Obsidian, Index 경계
4. `02-folder-module-rules.md`
   - 폴더와 모듈 배치 규칙
5. `03-naming-rules.md`
   - 파일, 클래스, 함수, 변수 Naming
6. `04-pydantic-validation-rules.md`
   - 외부·검증 경계의 Pydantic 규칙
7. `05-dataclass-internal-dto-rules.md`
   - 내부 DTO와 Dataclass 규칙
8. `06-typeddict-dictionary-rules.md`
   - TypedDict와 Raw Dictionary 제한
9. `07-type-strictness-rules.md`
   - Any, Optional, Union, Cast, Ignore 정책
10. `08-class-function-cohesion-rules.md`
    - 클래스 메서드 수, 함수·모듈 응집도
11. `09-schema-normalization-rules.md`
    - Raw 입력, 정규화, Canonical Contract
12. `10-storage-index-rules.md`
    - Obsidian Canonical Storage와 재구축 가능한 Index
13. `11-async-io-rules.md`
    - Async, Subprocess, File I/O 경계
14. `12-error-exception-rules.md`
    - 오류와 예외 설계
15. `13-lint-typecheck-test-rules.md`
    - 품질 게이트
16. `14-refactoring-rules.md`
    - 리팩토링 범위와 금지 사항
17. `15-agent-execution-rules.md`
    - GPT/Coding Agent 실행 규칙

## 읽는 방법

항상 읽는다.

- `규칙.md`
- `README.md`

작업과 관련된 세부 문서만 추가로 읽는다. 모든 문서를 매번 전부 읽어 Context를 낭비하지 않는다.
