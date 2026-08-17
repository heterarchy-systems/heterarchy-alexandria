# Context RAG Benchmark Baseline

- measured_at: 2026-08-05T10:33:40Z
- local_timezone: Asia/Seoul
- benchmark_surface: `/memory/contexts/retrieval/search`
- benchmark_tool: `backend/benchmarks/context_rag_api_benchmark.py`
- baseline_mode: Graph disabled, FTS·Vector·Embedding healthy

## 목적

Context RAG 성능을 감으로 판단하지 않고 동일한 HTTP 경로와 고정된 질의 집합으로 반복 측정하기 위한 기준선이다.

이 기준선은 다음 전체 경로를 포함한다.

```text
HTTP Request
→ FastAPI/Pydantic validation
→ ContextSearchService
→ FTS / Vector / Hybrid retrieval
→ scope and lifecycle filtering
→ optional graph lane boundary
→ Context Pack rendering
→ response serialization
```

SQL statement count처럼 결정적인 내부 계약은 Unit/Integration Test로 고정한다. 절대 latency는 장비·프로세스·모델 캐시 상태에 영향을 받으므로 CI 실패 기준으로 사용하지 않는다.

## 실행 방법

### 1. Graph-disabled 기준선 서버

```bash
cd backend
SERVICE_GRAPH_READ_MODEL=disabled \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 18012
```

### 2. API benchmark

```bash
cd backend
uv run python benchmarks/context_rag_api_benchmark.py \
  --base-url http://127.0.0.1:18012 \
  --project heterarchy-alexandria \
  --query "Graph-aware Context Retrieval" \
  --query "Retrieval Architecture" \
  --query "Neo4j Graph Read Model" \
  --query "heterarchy-alexandria Knowledge Graph" \
  --warmups 1 \
  --repetitions 7 \
  --output ../.chatgpt2codex/context-rag-baseline.json
```

인증이 필요한 서버는 토큰 값을 명령행에 직접 넣지 않는다.

```bash
export ALEXANDRIA_BENCHMARK_BEARER_TOKEN="..."
```

도구는 위 환경 변수만 읽어 `Authorization: Bearer` 헤더를 구성한다.

## 측정 환경

| 항목 | 값 |
|---|---|
| OS | macOS 26.5.2 arm64 |
| Python | 3.13.5 |
| Project filter | `heterarchy-alexandria` |
| Result limit | 5 |
| Warmup | 질의·전략별 1회 |
| Measured repetitions | 질의·전략별 7회 |
| FTS | HEALTHY |
| Vector | HEALTHY |
| Embedding | HEALTHY |
| Effective default | HYBRID |
| Obsidian embedding rows | 4,677 current / 0 stale / 0 missing |
| Graph | disabled for this baseline |
| Failed samples | 0 |

## 전략별 집계 기준선

각 값은 네 개 질의에서 나온 case-level 지표를 다시 집계한 값이다.

| Strategy | case p50 median | case p95 median | mean of case means | median response bytes | match range |
|---|---:|---:|---:|---:|---:|
| FTS_ONLY | 141.645 ms | 209.359 ms | 151.865 ms | 22,903 | 1–5 |
| VECTOR_ONLY | 605.465 ms | 665.359 ms | 607.651 ms | 15,456 | 1–3 |
| HYBRID | 661.654 ms | 729.793 ms | 655.712 ms | 44,594 | 5–5 |

이 수치는 서버 프로세스의 query embedding, SQLite/sqlite-vec 검색, 결과 mapping, Context Pack 작성과 JSON 직렬화를 합친 end-to-end latency다. Graph phase와 server RSS는 분리 측정하지 않는다.

## 질의별 결과

| Query | Strategy | p50 | p95 | Matches |
|---|---|---:|---:|---:|
| Graph-aware Context Retrieval | FTS_ONLY | 163.964 ms | 200.007 ms | 2 |
| Graph-aware Context Retrieval | VECTOR_ONLY | 626.186 ms | 722.210 ms | 1 |
| Graph-aware Context Retrieval | HYBRID | 653.057 ms | 789.204 ms | 5 |
| Retrieval Architecture | FTS_ONLY | 123.485 ms | 218.712 ms | 1 |
| Retrieval Architecture | VECTOR_ONLY | 597.507 ms | 689.762 ms | 1 |
| Retrieval Architecture | HYBRID | 592.708 ms | 661.600 ms | 5 |
| Neo4j Graph Read Model | FTS_ONLY | 138.260 ms | 149.080 ms | 3 |
| Neo4j Graph Read Model | VECTOR_ONLY | 599.256 ms | 640.955 ms | 2 |
| Neo4j Graph Read Model | HYBRID | 670.252 ms | 704.109 ms | 5 |
| heterarchy-alexandria Knowledge Graph | FTS_ONLY | 145.031 ms | 222.456 ms | 5 |
| heterarchy-alexandria Knowledge Graph | VECTOR_ONLY | 611.673 ms | 627.045 ms | 3 |
| heterarchy-alexandria Knowledge Graph | HYBRID | 676.096 ms | 755.476 ms | 5 |

## Query Store 최적화 기준선

동일 로컬 SQLite index와 동일 FTS query에서 결과 10개를 조회한 microbenchmark다.

| 지표 | 변경 전 | 변경 후 |
|---|---:|---:|
| SQL statements | 19 | 4 |
| Median latency | 27.032 ms | 14.6–15.8 ms |
| Python peak allocation | 162.8 KiB | 152.2–152.9 KiB |

구현 변경은 다음과 같다.

- 후보별 Note·Chunk N+1 조회를 bounded bulk hydration으로 변경
- 요청 limit 단위 batch 처리로 peak allocation 제한
- 결과에 필요하지 않은 embedding metadata column 미적재
- Note별 ContextRecord 변환을 검색 요청 내 한 번으로 제한
- 동일 Search Source에서 FTS table 준비 DDL을 한 번만 실행

## SQL 회귀 계약

`tests/memory/test_context_obsidian_rag_source.py`가 다음 계약을 고정한다.

| Recall path | SQL contract |
|---|---:|
| FTS first call | 4 statements |
| FTS repeated call on same source | 3 statements |
| Vector call | 3 statements |

Vector 3 statements는 다음 경계를 의미한다.

```text
Vector ranking query
+ ranked Note bulk load
+ ranked Chunk bulk load
```

## Graph-enabled 측정 상태

Graph-enabled 로컬 실행은 기준선에서 제외했다.

현재 Mac 호스트의 resolved Neo4j URI는 Docker network hostname인 `neo4j:7687`을 사용한다. 호스트에서는 해당 이름을 DNS resolve할 수 없어 Neo4j driver transaction retry가 반복됐다.

관찰된 영향:

- 검색 요청이 정상 FTS·Vector 결과를 보유해도 optional Graph lane에서 장시간 대기
- 개별 요청 완료 시간이 약 32–59초까지 증가
- benchmark client timeout과 실행 도구의 upstream timeout 발생

따라서 Graph-enabled 기준선은 다음 중 하나가 충족된 환경에서 별도로 측정한다.

1. Backend와 Neo4j를 같은 Docker network에서 실행
2. Mac 호스트에서 접근 가능한 Neo4j URI를 설정
3. Graph provider의 fail-fast timeout/retry 정책을 별도 작업으로 확정

Graph가 정상 연결된 실행에서는 benchmark JSON의 `graph_evidence_match_count_max`가 0보다 큰지 함께 확인한다. 현재 도구는 Graph lane의 존재와 end-to-end 영향을 확인하지만 Graph phase만의 시간을 분리하지는 않는다.

## 해석 규칙

- 다른 장비나 다른 모델 캐시 상태의 절대 latency를 직접 비교하지 않는다.
- 동일 질의, 동일 project, 동일 limit, 동일 warmup/repetition으로 비교한다.
- `VECTOR_ONLY` 요청이 `effective_strategy=FTS_ONLY`로 내려가면 건강한 Vector 기준선으로 인정하지 않는다.
- warning 또는 failed sample이 하나라도 있으면 정상 기준선과 분리한다.
- 응답 시간이 개선돼도 match count가 감소하면 성능 개선으로 단정하지 않는다.
- Graph-disabled와 Graph-enabled 결과를 같은 표의 단일 수치로 합치지 않는다.

## 현재 판단

Query Store의 N+1과 중복 mapping 비용은 제거됐다. 현재 end-to-end 결과에서는 FTS보다 Vector와 Hybrid가 더 큰 latency를 보이지만, benchmark 도구는 query embedding inference와 sqlite-vec query를 분리하지 않는다. 다음 최적화는 별도의 phase timing 근거가 생긴 후 결정한다.

Neo4j가 연결되지 않았을 때 optional Graph lane이 수십 초간 retry하는 현상은 별도의 높은 우선순위 성능·복구 과제다. 이 기준선 작업에서는 Graph 계약이나 driver 설정을 임의 변경하지 않았다.
