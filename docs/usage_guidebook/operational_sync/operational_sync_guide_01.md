# Operational Sync Guide 01 — PostgreSQL, Obsidian, Embedding 상태 복구

## 목적

heterarchy-alexandria에서 Obsidian Markdown을 원본으로 유지하면서 PostgreSQL 검색/그래프 source와 embedding/vector index를 안전하게 동기화한다.

이 가이드는 다음 증상에서 사용한다.

- `/operations/readiness`가 `BLOCKED` 또는 `DEGRADED_FTS_ONLY`다.
- `/memory/contexts/rag/status`의 `embedding`이 `REINDEX_REQUIRED`다.
- `source_statuses[].stale_rows` 또는 `missing_rows`가 0보다 크다.
- `/obsidian/status`의 `stale_notes` 또는 `error_notes`가 0보다 크다.
- PostgreSQL index가 Obsidian Markdown과 어긋난 것 같다.

## 핵심 원칙

- Obsidian Markdown이 원본이다.
- PostgreSQL FTS, vector, embedding, Rust graph projection은 재생성 가능한 index/state다.
- queued embedding reindex는 source note/context를 삭제하지 않고 embedding metadata/vector만 갱신한다.
- PostgreSQL, Redis, Vault를 API 밖에서 직접 수정하지 않는다.
- 최종 목표는 `/operations/readiness`가 `READY`, `ready=true`, warnings/blockers/next_actions가 모두 빈 배열인 상태다.

## 0. 서비스 생존 확인

```bash
curl -sS http://127.0.0.1:8000/health/live
```

기대:

```json
{"status":"ok"}
```

## 1. 현재 상태 확인

```bash
curl -sS http://127.0.0.1:8000/obsidian/status | jq
curl -sS http://127.0.0.1:8000/memory/contexts/rag/status | jq
curl -sS http://127.0.0.1:8000/operations/readiness | jq
```

확인할 필드:

- `obsidian.status`: `stale_notes`, `error_notes`
- `rag.status`: `fts`, `vector`, `embedding`, `default_strategy`, `warnings`
- `rag.source_statuses[]`: `source_name`, `total_rows`, `current_rows`, `stale_rows`, `missing_rows`
- `operations.readiness`: `status`, `ready`, `warnings`, `blockers`, `next_actions`

## 2. Obsidian → PostgreSQL 검색/그래프 source 재색인

Obsidian Markdown 파일 변경이나 stale note가 있으면 먼저 vault index를 재구축한다.

```bash
curl -sS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

이 작업은 PostgreSQL `obsidian_files`와 `obsidian_edges`를 갱신하고
PostgreSQL/Rust graph projection 결과를 반환한다. 별도 graph database나
Python compute fallback은 사용하지 않는다.

일반 검색은 현재 인덱스를 읽기만 하며 자동 재색인하지 않는다. 검색과
함께 명시적으로 갱신해야 하는 진단 상황에서만 HTTP 검색 요청에
`"refresh": true`를 지정한다. 정상 운영에서는 이 옵션 대신 위의 전용
rebuild endpoint를 사용한다.

응답 예:

```json
{
  "files_seen": 179,
  "files_indexed": 148,
  "files_skipped": 31,
  "stale_marked": 0,
  "errors": []
}
```

이후 다시 확인한다.

```bash
curl -sS http://127.0.0.1:8000/obsidian/status | jq
```

## 3. Queued embedding reindex

`embedding=REINDEX_REQUIRED`, `stale_rows>0`, `missing_rows>0`이면 bounded
maintenance job을 queue에 등록한다.

```bash
job_json="$(curl -fsS -X POST \
  http://127.0.0.1:8000/operations/maintenance/embedding-reindex/jobs \
  -H 'Content-Type: application/json' \
  --data '{"requested_by":"operator","source_id":"operational-sync-manual","limit":1000,"force":false}')"
printf '%s\n' "$job_json" | jq
job_id="$(printf '%s' "$job_json" | jq -r '.job_id')"
curl -fsS "http://127.0.0.1:8000/operations/maintenance/jobs/${job_id}" | jq
```

응답에서 확인할 필드:

- `status`: `QUEUED`, `RUNNING`, `SUCCEEDED`, or `FAILED`
- `job_id`: persisted maintenance job identity
- `source_id`: stable duplicate-suppression key

정상 기대:

```json
{"status":"SUCCEEDED","job_id":"<job-id>"}
```

## 4. 재색인 후 새 embedding gap이 생긴 경우

Vault reindex 후 `rag/status`에서 새 `missing_rows`가 생길 수 있다. 이때는
3번의 queued embedding reindex를 다시 실행한다.

```bash
curl -sS http://127.0.0.1:8000/memory/contexts/rag/status | jq
```

`obsidian_vault.stale_rows=0`, `obsidian_vault.missing_rows=0`이 될 때까지
job status와 RAG status를 확인한다.

## 5. PostgreSQL/Rust graph projection rebuild와 진단

Vault reindex 결과가 stale, failed, skipped이거나 별도 진단이 필요하면
PostgreSQL/Rust graph projection을 재구축한다.

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/obsidian/graph/projection/rebuild \
  | jq '{status, scanned, indexed, skipped, issue_total, issue_counts, errors}'
curl -sS http://127.0.0.1:8000/obsidian/graph/projection/status \
  | jq '{status, node_count, edge_count, last_run_issue_total, last_run_issue_counts, errors}'
```

`issue_total`/`issue_counts`는 깨진 링크처럼 투영에서 제외된 비치명적 원본
진단이다. `errors`는 실제 rebuild 실패만 담는다. 개별 진단은 기본 응답에서
생략되므로 조사할 때만 최대 500개 이하의 bounded sample을 요청한다.
깨진 링크 진단에서 `note_id`는 링크를 가진 원본 note, `relative_path`는
찾지 못한 target, `edge_id`는 PostgreSQL graph-source edge 식별자다.

```bash
curl -sS -X POST \
  'http://127.0.0.1:8000/obsidian/graph/projection/rebuild?include_issue_details=true&issue_limit=100' \
  | jq '{issue_total, issue_counts, issues_truncated, issues, errors}'
```

Vault/embedding/graph 유지보수 작업은 동시에 실행하지 않는다. 이미 다른
유지보수 작업이 실행 중이면 서버가 대기하지 않고 HTTP `409`를 반환하므로,
현재 작업 종료 후 순서대로 다시 실행한다.

## 6. Direct cache repair is not supported

PostgreSQL, Redis, and the Vault are owned runtime boundaries. Do not delete or
rewrite index rows directly with a local database client. Re-run the bounded
Vault reindex or embedding maintenance job, then inspect the returned evidence
and readiness state.

## 7. 최종 검증

```bash
curl -sS http://127.0.0.1:8000/obsidian/status | jq
curl -sS http://127.0.0.1:8000/memory/contexts/rag/status | jq
curl -sS http://127.0.0.1:8000/operations/readiness | jq
```

최종 기대:

```json
{
  "status": "READY",
  "ready": true,
  "warnings": [],
  "blockers": [],
  "next_actions": []
}
```

대표 HYBRID 검색도 확인한다.

```bash
curl -sS -X POST http://127.0.0.1:8000/memory/contexts/retrieval/search \
  -H "Content-Type: application/json" \
  --data '{
    "query": "운영 안정성 자동 복구 루프",
    "strategy": "HYBRID",
    "limit": 3,
    "project": "heterarchy-alexandria"
  }' | jq '{strategy, effective_strategy, warnings, matches: [.matches[] | {context_id: .context.id, title: .context.title, vector_score, why_retrieved}]}'
```

정상 기대:

- `effective_strategy`가 `HYBRID`
- `warnings`가 빈 배열
- 첫 결과에 `obsidian:prd_operational_readiness_recovery_v0_1` 또는 관련 PRD note가 포함
- `why_retrieved`가 semantic embedding/vector match를 설명

## 8. readiness endpoint 500이면

`/operations/readiness`가 500이고 로그에 `ContextEmbeddingSourceStatusResponse` validation error가 보이면 schema boundary 변환 문제다.

수정 포인트:

- `backend/app/operations/interface/schemas/operations/operational_readiness_schema.py`
- 내부 `ContextEmbeddingSourceStatus` dataclass를 직접 `model_validate()`하지 말고 `source_status_payload()`로 dict payload로 바꾼다.

검증:

```bash
cd backend
uv run pytest -q tests/operations/test_operational_readiness_router.py::test_operational_readiness_route_returns_snapshot_payload
make ci
```
