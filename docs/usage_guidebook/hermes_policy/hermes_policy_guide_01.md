# Hermes Operating Contract 01 — Alexandria local-first 사용

## 목적

Hermes가 heterarchy-alexandria를 local-first로 사용할 때의 호출 순서와
Memory Steward 상태 확인 경계를 명확히 한다.

기본 운영 원칙은 **local-first / Alexandria-when-needed**다. Hermes는 현재
대화와 로컬 context를 먼저 사용하고, 필요한 경우에만 현재 MCP surface와
Memory Steward를 호출한다.

## 상태 확인

```bash
heterarchy-alexandria memory-steward readiness --project heterarchy-alexandria
curl -fsS http://127.0.0.1:8000/operations/readiness | jq
```

예상 출력 일부:

```json
{"status":"READY","ready":true}
```

## Runtime 해석

Hermes가 Alexandria를 사용할 때 해야 할 일:

1. 현재 대화, local memory, loaded/local/built-in skill을 먼저 확인한다.
2. 그 정보가 충분하면 Alexandria를 쓰지 않는다.
3. 로컬 정보가 부족하거나 이전 작업/결정/핸드오프/버그 원인/장기기억이 필요하면 current Memory Compact를 먼저 읽는다.
4. 그래도 부족하면 Context Vault recall/RAG로 좁게 찾고, reusable capability가 필요할 때 library skill/prompt search를 사용한다.
5. 중요한 decision, handoff, bug root cause, reusable workflow는 Alexandria에 저장한다.
6. Memory Steward compact/reconciliation은 current MCP tools 또는 등록된
   `memory-steward` CLI를 사용한다.

## Session scope

사용자가 이번 작업에서 Alexandria를 사용하지 말라고 하면 해당 session에서
MCP 호출을 건너뛴다. 저장된 backend 상태나 인증 정보를 임의로 변경하지 않는다.

```text
이번 작업에서는 Alexandria 쓰지 말고 해.
```

다시 사용하라는 명시 요청이 있으면 현재 MCP surface와 Memory Steward를
재개한다.
