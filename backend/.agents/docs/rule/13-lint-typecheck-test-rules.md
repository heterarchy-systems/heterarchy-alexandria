# Lint, Typecheck, and Test Rules

## 저장소 명령 발견

작업 전에 다음에서 공식 명령을 찾는다.

- `pyproject.toml`
- `Makefile`
- `justfile`
- CI Workflow
- README
- 기존 개발 문서

OMX-agent-adapter의 Ruff, Pyrefly 명령을 heterarchy-alexandria에 자동 복사하지 않는다.

## 품질 게이트

의미 있는 Production 변경은 다음을 통과해야 한다.

1. Format 또는 Format Check
2. Lint
3. Static Typecheck
4. 관련 Unit Test
5. 관련 Integration Test
6. 필요 시 Full Test Suite

## Type Checker

저장소가 현재 사용하는 Type Checker를 우선한다.

기존 Type Checker가 없다면 별도 작업에서 선택한다. 기능 구현 중 임의로 Pyrefly, Mypy, Pyright를 추가하지 않는다.

## Source와 Test

Production Code는 Test보다 엄격하게 본다.

Test Fixture의 편의를 위해 Production 타입을 약화하지 않는다.

## Baseline

변경 전 관련 Test를 실행한다.

실패를 다음으로 분류한다.

- pre-existing
- change-induced
- environment
- flaky

## Suppression

- Broad `# noqa` 금지
- Broad `type: ignore` 금지
- 설정 완화로 Local Error를 숨기지 않음
- 필요한 Suppression은 가장 좁은 범위와 이유를 사용

## 완료 보고

실행한 명령, Exit Code, 실패 개수, 통과 개수를 기록한다.

Test를 작성했지만 실행하지 않았으면 `IMPLEMENTED`다.
