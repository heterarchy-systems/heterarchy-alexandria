# Hermes Policy Guide 01 — Alexandria 사용 ON/OFF

## 목적

사용자가 Hermes에게 heterarchy-alexandria를 쓰게 할지 말지를 명확히 제어한다.

## policy 위치

```text
~/.hermes/heterarchy-alexandria/policy.yaml
```

기본값은 ON이다. 단, ON의 의미는 “항상 Alexandria부터 호출”이 아니라 **local-first / Alexandria-when-needed**다.

```yaml
enabled: true
mode: local_first_library_when_needed
```

## 상태 확인

```bash
heterarchy-alexandria --json hermes policy status --hermes-home "$HOME/.hermes"
```

예상 출력 일부:

```json
{
  "enabled": true,
  "mode": "local_first_library_when_needed",
  "self_acquisition_enabled": true,
  "librarian_optional": true,
  "hermes_self_acquisition_fallback": true
}
```

## Runtime 해석

`enabled: true`일 때 Hermes가 해야 할 일:

1. 현재 대화, local memory, loaded/local/built-in skill을 먼저 확인한다.
2. 그 정보가 충분하면 Alexandria를 쓰지 않는다.
3. 로컬 정보가 부족하거나 이전 작업/결정/핸드오프/버그 원인/장기기억이 필요하면 current Memory Compact를 먼저 읽는다.
4. 그래도 부족하면 Context Vault recall/RAG로 좁게 찾고, reusable capability가 필요할 때 library skill/prompt search를 사용한다.
5. 중요한 decision, handoff, bug root cause, reusable workflow는 Alexandria에 저장한다.
6. librarian delegation은 optional이며 기본적으로 명시 요청이 있을 때만 사용한다. Memory Compact/Context Vault 조회는 librarian delegation이 아니다.

## 끄기

```bash
heterarchy-alexandria --json hermes policy disable --hermes-home "$HOME/.hermes"
```

이후 Hermes는 다음 경우를 제외하고 Alexandria를 쓰지 않아야 한다.

- status/diagnostics 확인
- 사용자가 명시적으로 Alexandria 사용을 요청한 경우

## 다시 켜기

```bash
heterarchy-alexandria --json hermes policy enable --hermes-home "$HOME/.hermes"
```

## Hermes에게 말하는 예

```text
Alexandria 사용하지 마.
```

Hermes가 해야 할 일:

```bash
heterarchy-heterarchy-alexandria policy disable
```

```text
다시 Alexandria 써.
```

Hermes가 해야 할 일:

```bash
heterarchy-heterarchy-alexandria policy enable
```

## session-only off

아래 표현은 global policy를 바꾸지 않고 현재 작업에서만 적용한다.

```text
이번 작업에서는 Alexandria 쓰지 말고 해.
```

이 경우 Hermes는 현재 task/session에서만 Alexandria tool을 피하고, `policy.yaml`은 수정하지 않는다.
