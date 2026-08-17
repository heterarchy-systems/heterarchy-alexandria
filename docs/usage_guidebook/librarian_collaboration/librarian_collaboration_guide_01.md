# Librarian Collaboration Guide 01 — 사서를 optional 협업자로 쓰기

## 목적

사서(librarian)를 필수 의존성이 아니라 품질 보조/위임 협업자로 사용하는 법을 정리한다.

## 핵심 원칙

```text
사서가 있으면 협업 가능하다.
사서가 없어도 Hermes는 멈추지 않는다.
Hermes self-acquisition이 fallback이다.
```

## 언제 사서를 쓰나

- 조사 범위가 넓고 Hermes가 현재 작업으로 바쁠 때
- 후보 skill/prompt를 제3자 시각으로 리뷰하고 싶을 때
- route-preview상 적절한 provider/profile이 준비되어 있을 때
- 사용자가 명시적으로 librarian collaboration을 요청했을 때

## 언제 사서를 쓰지 않나

- policy가 `enabled: false`인 경우
- 사용자가 이번 작업에서 librarian 금지를 명시한 경우
- operator key가 없어서 protected route가 401인 경우
- 간단한 read-only 확인이면 CLI/MCP search로 충분한 경우

## operator key 확인

protected librarian/settings route는 operator key가 필요하다.

```bash
heterarchy-alexandria --json librarian providers list
heterarchy-alexandria --json librarian profiles list
```

`HTTP 401: Operator API key required`가 나오면 현재 process 환경 또는 Hermes MCP env에 operator key가 없는 것이다. 실제 값은 출력하지 말고 presence/length와 command success로만 확인한다.

## 협업 예

```bash
heterarchy-alexandria --json librarian ask   "이 후보 skill의 누락된 pitfall을 한 줄로 검토해 주세요."   --delegate-to-librarian   --agent-name Hermes   --task-summary "Skill candidate review"
```

## fallback 예

사서가 실패하면 Hermes가 해야 할 일:

```text
1. 실패 원인을 짧게 기록한다. 예: librarian unavailable / operator key missing.
2. 작업을 중단하지 않는다.
3. Hermes가 직접 조사해 candidate draft를 만든다.
4. job id, result status, evidence, resume context id를 보고한다.
```
