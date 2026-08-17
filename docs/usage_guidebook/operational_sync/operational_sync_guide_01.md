# Operational Sync Guide 01 — SQLite, Obsidian, Embedding 상태 복구

## 목적

heterarchy-alexandria에서 Obsidian Markdown을 원본으로 유지하면서 SQLite 검색 캐시와 embedding/vector index를 안전하게 동기화한다.

이 가이드는 다음 증상에서 사용한다.

- `/operations/readiness`가 `BLOCKED` 또는 `DEGRADED_FTS_ONLY`다.
- `/memory/contexts/rag/status`의 `embedding`이 `REINDEX_REQUIRED`다.
- `source_statuses[].stale_rows` 또는 `missing_rows`가 0보다 크다.
- `/obsidian/status`의 `stale_notes` 또는 `error_notes`가 0보다 크다.
- SQLite cache가 Obsidian Markdown과 어긋난 것 같다.

## 핵심 원칙

- Obsidian Markdown이 원본이다.
- SQLite, FTS, vector, embedding은 재생성 가능한 index/cache다.
- soft rebuild는 source note/context를 삭제하지 않고 chunk embedding metadata/vector만 갱신한다.
- stale SQLite cache row를 정리하기 전에는 DB 백업을 만든다.
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

## 2. Obsidian → SQLite 검색 캐시 재색인

Obsidian Markdown 파일 변경이나 stale note가 있으면 먼저 vault index를 재구축한다.

```bash
curl -sS -X POST http://127.0.0.1:8000/obsidian/index/rebuild | jq
```

이 작업은 SQLite `obsidian_edges`를 Neo4j 재구축용 source cache로만
갱신한다. Graph traversal/evidence가 필요하면 Neo4j를 활성화한 뒤 graph
projection rebuild를 별도로 실행한다.

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

## 3. Embedding soft rebuild

`embedding=REINDEX_REQUIRED`, `stale_rows>0`, `missing_rows>0`이면 soft rebuild를 실행한다.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/memory/contexts/retrieval/soft-rebuild?limit=1000&verification_query=운영%20안정성%20자동%20복구%20루프&project=heterarchy-alexandria" | jq
```

응답에서 확인할 필드:

- `source_preservation`: source 보존 설명
- `hard_delete_performed`: 반드시 `false`
- `source_status_before`
- `reindex.scanned`, `reindex.updated`, `reindex.warnings`
- `source_status_after`
- `verification_matches`
- `verification_context_ids`
- `warnings`

정상 기대:

```json
{
  "mode": "soft_embedding_vector_rebuild",
  "hard_delete_performed": false,
  "reindex": {"warnings": []},
  "verification_matches": 3,
  "warnings": []
}
```

## 4. 재색인 후 새 embedding gap이 생긴 경우

Vault reindex 후 `rag/status`에서 새 `missing_rows`가 생길 수 있다. 이때는 3번 soft rebuild를 한 번 더 실행한다.

```bash
curl -sS http://127.0.0.1:8000/memory/contexts/rag/status | jq
```

`obsidian_vault.stale_rows=0`, `obsidian_vault.missing_rows=0`이 될 때까지 soft rebuild를 반복한다.

## 5. Neo4j graph projection rebuild와 진단

Graph read model이 `neo4j`이면 vault reindex 뒤 projection을 재구축한다.

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
찾지 못한 target, `edge_id`는 SQLite source-cache edge 식별자다.

```bash
curl -sS -X POST \
  'http://127.0.0.1:8000/obsidian/graph/projection/rebuild?include_issue_details=true&issue_limit=100' \
  | jq '{issue_total, issue_counts, issues_truncated, issues, errors}'
```

Vault/embedding/graph 유지보수 작업은 동시에 실행하지 않는다. 이미 다른
유지보수 작업이 실행 중이면 서버가 대기하지 않고 HTTP `409`를 반환하므로,
현재 작업 종료 후 순서대로 다시 실행한다.

## 6. stale SQLite cache row 정리

`/obsidian/index/rebuild` 후에도 `/obsidian/status`의 `stale_notes`가 남고, 해당 파일들이 실제 vault에 없으면 SQLite cache row만 남은 상태다.

먼저 백업한다.

```bash
backup="backend/data/alexandria_hermes.pre-stale-cache-clean-$(date -u +%Y%m%dT%H%M%SZ).db"
cp backend/data/alexandria_hermes.db "$backup"
echo "$backup"
```

stale row와 종속 파생 row를 확인한다.

```bash
sqlite3 backend/data/alexandria_hermes.db <<'SQL'
.headers on
.mode column
SELECT index_status, COUNT(*) AS count FROM obsidian_files GROUP BY index_status;
SELECT note_id, relative_path, index_status
FROM obsidian_files
WHERE index_status != 'indexed'
ORDER BY relative_path;
SELECT 'chunks' AS table_name, COUNT(*) AS stale_related
FROM obsidian_chunks
WHERE note_id IN (SELECT note_id FROM obsidian_files WHERE index_status='stale');
SELECT 'edges_source' AS table_name, COUNT(*) AS stale_related
FROM obsidian_edges
WHERE source_note_id IN (SELECT note_id FROM obsidian_files WHERE index_status='stale');
SELECT 'edges_target' AS table_name, COUNT(*) AS stale_related
FROM obsidian_edges
WHERE target_note_id IN (SELECT note_id FROM obsidian_files WHERE index_status='stale');
SQL
```

모두 실제 Markdown 파일이 없는 cache row라면 정리한다.

```bash
sqlite3 backend/data/alexandria_hermes.db <<'SQL'
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE stale_note_ids(note_id TEXT PRIMARY KEY);
INSERT INTO stale_note_ids(note_id)
SELECT note_id FROM obsidian_files WHERE index_status='stale';
DELETE FROM obsidian_edges
WHERE source_note_id IN (SELECT note_id FROM stale_note_ids)
   OR target_note_id IN (SELECT note_id FROM stale_note_ids);
DELETE FROM obsidian_files WHERE note_id IN (SELECT note_id FROM stale_note_ids);
COMMIT;
PRAGMA foreign_key_check;
SQL
```

이 정리는 Obsidian Markdown을 삭제하지 않는다. SQLite의 rebuildable cache만 정리한다.

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
