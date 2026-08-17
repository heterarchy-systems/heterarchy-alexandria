# Context Recall Guide 01 — capture → recall → inspect

## 목적

처음 사용하는 사람이 heterarchy-alexandria의 핵심 가치인 **durable context 재사용**을 5분 안에 확인한다.

이 가이드는 설치가 끝난 뒤 다음 성공 상태를 만든다.

```text
context 저장
→ FTS/HYBRID recall
→ Context Pack 확인
→ UI에서 원문/chunk/RAG 상태 확인
```

## 전제

- backend가 `http://localhost:8000`에서 실행 중이다.
- `heterarchy-alexandria` CLI 또는 `./bin/heterarchy-alexandria`를 실행할 수 있다.
- 실제 secret/API key/token 값은 예제에 넣지 않는다.

## 1. 첫 context 저장

```bash
cat > /tmp/alexandria-first-context.md <<'MD'
# First Alexandria context

heterarchy-alexandria is a local-first agent library.
Use Context Vault for durable decisions, handoffs, plans, memory compacts, and reusable agent context.
MD

heterarchy-alexandria --base-url http://localhost:8000 context save \
  --title "First Alexandria context" \
  --kind DECISION \
  --project heterarchy-alexandria \
  --content-file /tmp/alexandria-first-context.md
```

## 2. recall 확인

처음 smoke test는 embedding/model 상태와 무관하게 재현되도록 `FTS_ONLY`를 사용한다.

```bash
heterarchy-alexandria --base-url http://localhost:8000 context recall \
  "durable decisions handoffs memory compacts" \
  --strategy FTS_ONLY \
  --project heterarchy-alexandria \
  --limit 3
```

성공 기준:

- 결과에 `Context Pack` 또는 matching context/chunk 정보가 나온다.
- 저장한 title 또는 content 일부가 검색된다.

## 3. RAG 상태 확인

```bash
heterarchy-alexandria --base-url http://localhost:8000 context doctor-rag
```

해석:

- `FTS` healthy면 기본 텍스트 recall 가능.
- `vector`/`embedding`이 degraded여도 FTS smoke test는 가능하다.
- `HYBRID`는 vector/embedding 상태가 정상일 때 기본 전략으로 적합하다.

## 4. UI에서 확인

브라우저에서 확인한다.

```text
heterarchy-alexandria context recall "<query>" --json
```

`/contexts`에서 저장된 context가 보여야 한다. FTS/vector/RAG 상태는 `context doctor-rag`로 확인한다.

## 흔한 실패

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| backend 연결 실패 | `/health/ready` 확인 | backend 실행 또는 `--base-url` 수정 |
| recall 결과 없음 | 저장 project/kind/query 확인 | `--project`를 빼고 다시 검색 |
| vector degraded | `context doctor-rag` 확인 | FTS_ONLY로 smoke test 후 embedding 설정 점검 |
| recall 결과가 비어 있음 | project/kind/filter 확인 | 더 좁은 query 또는 RAG 상태 확인 |
