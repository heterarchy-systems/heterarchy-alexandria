# Context RAG 성능·검색 품질 기준선 가이드 02

이 문서는 MCP v2 modernization 이후 Alexandria의 **검색 정확도와 응답시간을 같은 실행에서 측정하는 현재 가이드**다.

과거 SQLite/sqlite-vec 기준 측정은 [context_rag_benchmark_guide_01.md](context_rag_benchmark_guide_01.md)에 역사적 기록으로 남긴다. 현재 runtime authority는 다음과 같다.

```text
Obsidian Markdown
→ canonical knowledge storage

PostgreSQL FTS / pgvector / embedding index
→ rebuildable retrieval state

PostgreSQL indexed graph source + Rust graph compute
→ rebuildable graph projection cache

Redis
→ ephemeral maintenance queue/cache/coordination

MCP Python SDK v2
→ GPT/agent protocol boundary
```

Benchmark rows named `Neo4j 기능 05 Graph-aware Context Retrieval` retain a
historical canonical note title from the corpus; they do not describe a current
Neo4j runtime dependency.

## 1. CI에서 검증하는 것과 실측하는 것을 분리한다

Canonical CI는 benchmark 코드 자체가 재현 가능하고 결정적으로 동작하는지만 검사한다.

```bash
cd backend
make benchmark_check
```

이 target은 다음을 검증한다.

- Golden Query JSON validation
- nearest-rank p50/p95 계산
- Recall@1 / Recall@3 / MRR 계산
- 반복 실행 ranking stability 계산
- Context id와 Obsidian title 기반 기대값
- MCP v2 결과와 nested transport error parsing
- 두 benchmark CLI의 module entrypoint

**절대 latency 숫자는 CI pass/fail threshold로 사용하지 않는다.** 머신 부하, 모델 cache, Docker 상태에 따라 변하기 때문이다. latency는 JSON 보고서로 기록하고 동일 환경의 이전 결과와 비교한다.

## 2. Golden Query 파일 준비

예제를 복사한다.

```bash
cd backend
mkdir -p build/benchmarks
cp benchmarks/golden_cases.example.json \
  build/benchmarks/golden-cases.local.json
```

`build/`는 Git에서 제외된다. 개인 Vault의 note title이나 Context id를 repository에 올리지 않고 로컬 기준선으로 유지할 수 있다.

Obsidian 문서는 안정적인 title을 사용한다.

```json
{
  "query": "Memory Steward의 CURRENT 생명주기는?",
  "project": "heterarchy-alexandria",
  "expected_titles": [
    "Alexandria Memory Steward Contract"
  ]
}
```

Context Vault 문서는 stable Context id를 사용한다.

```json
{
  "query": "이 프로젝트에서 합의한 storage authority는?",
  "project": "heterarchy-alexandria",
  "expected_context_ids": [
    "stable-context-id"
  ]
}
```

한 query에 여러 정답 문서가 허용되면 배열에 모두 넣는다. 같은 query를 두 번 정의하지 않는다.

## 3. HTTP Context RAG 기준선 실행

로컬 backend가 실행 중인지 먼저 확인한다.

```bash
curl -fsS http://127.0.0.1:8000/health/live
```

전체 전략을 한 번에 측정할 수 있다.

```bash
cd backend
uv run python -m benchmarks.context_rag_api_benchmark \
  --base-url http://127.0.0.1:8000 \
  --golden-cases build/benchmarks/golden-cases.local.json \
  --limit 5 \
  --warmups 1 \
  --repetitions 5 \
  --timeout-seconds 30 \
  --output build/benchmarks/context-rag.json
```

Vault가 크거나 한 전략이 느리면 전략별로 나눠 실행한다. 이렇게 하면 이미 끝난 측정 결과를 잃지 않는다.

```bash
for strategy in FTS_ONLY VECTOR_ONLY HYBRID; do
  uv run python -m benchmarks.context_rag_api_benchmark \
    --base-url http://127.0.0.1:8000 \
    --golden-cases build/benchmarks/golden-cases.local.json \
    --strategy "$strategy" \
    --limit 5 \
    --warmups 1 \
    --repetitions 5 \
    --timeout-seconds 30 \
    --output "build/benchmarks/context-rag-${strategy}.json"
done
```

인증된 원격 endpoint라면 token을 직접 command에 넣지 않는다.

```bash
export ALEXANDRIA_BENCHMARK_BEARER_TOKEN='<oauth-access-token>'
```

보고서에는 token 값이나 credential이 저장되지 않는다.

## 4. 보고서 해석

핵심 quality 지표는 다음과 같다.

| 지표 | 의미 |
| --- | --- |
| `recall_at_1` | 첫 결과가 허용된 정답인가 |
| `recall_at_3` | 상위 3개 안에 정답이 있는가 |
| `mean_reciprocal_rank` | 정답이 얼마나 앞 순위에 있는가 |
| `ranking_stable` | 반복 실행에서 순서가 동일한가 |
| `unstable_case_count` | 전략별로 순서가 흔들린 query 수 |

Latency는 각 query/strategy별 p50, p95, mean, min, max로 기록한다. 실패 요청은 성공 latency에 섞지 않고 `failed_samples`와 `failures`로 분리한다.

Graph evidence가 반환되더라도 정답 문서가 검색되지 않았다면 품질 성공으로 간주하지 않는다.

## 5. MCP v2 read-only latency 실행

기본 tool은 mutation이 없는 `alexandria_rag_status`다.

```bash
cd backend
export ALEXANDRIA_BENCHMARK_BEARER_TOKEN='<oauth-access-token>'
uv run python -m benchmarks.mcp_readonly_benchmark \
  --endpoint http://127.0.0.1:8000/mcp \
  --tool-name alexandria_rag_status \
  --warmups 1 \
  --repetitions 5 \
  --output build/benchmarks/mcp-readonly.json
```

다음 단계를 분리해서 기록한다.

```text
transport_connect
initialize
list_tools
tools/call
```

OAuth token이 없는 별도 shell process에서는 transport context 생성 후 `initialize`가 거절될 수 있다. 이것은 GPT connector의 연결 실패와 동일하지 않다. benchmark process가 사용할 bearer token을 별도 환경변수로 전달해야 한다.

## 6. 2026-08-21 post-modernization 검색 품질 기준선

### 6.1 최초 측정의 scope 오류

최초 Golden Query 실행은 project-scoped Obsidian note를 `project` 없이 조회했다. Alexandria의 Context recall 기본 정책은 `project=None`일 때 `GLOBAL` scope만 선택하므로 이 측정의 Recall `0`은 검색 engine 품질만을 의미하지 않았다.

따라서 다음 결과는 품질 기준선에서 폐기한다.

```text
project-scoped 정답 + project 미지정
→ recall_scopes = GLOBAL
→ 정답 문서가 candidate 대상에서 제외될 수 있음
→ Recall@K 평가 무효
```

Golden Query 파일은 각 정답 note의 실제 recall scope를 명시한다. case-level `project`가 있으면 전역 `--project`보다 우선한다.

### 6.2 올바른 project scope로 다시 측정한 FTS 기준선

> **Benchmark provenance:** 이 절의 Project Index 행과 이어지는 동일 benchmark 행의 수치는 리브랜딩 이전에 측정한 역사적 값이다. 표시는 현재 canonical 이름으로 정규화했으며, release gate로 재사용할 때는 현재 query/title로 다시 측정한다.

4개의 실제 canonical Obsidian note를 올바른 project scope에서 `FTS_ONLY`, limit 5, 1 sample로 재측정했다.

```text
Recall@1 = 0.75
Recall@3 = 1.00
MRR      = 0.875
ranking instability = 0
```

| Golden Query | Project | Expected rank | 관찰 |
| --- | --- | ---: | --- |
| Engineering Modernization Contract | `heterarchy-alexandria` | 1 | 정답 1위 |
| Neo4j 기능 05 Graph-aware Context Retrieval | `heterarchy-alexandria` | 1 | 정답 1위 |
| Alexandria Memory Steward Contract | `heterarchy-alexandria` | 2 | Daily Health가 본문 빈도로 1위 |
| heterarchy-alexandria Project Index (pre-rebrand measurement) | `heterarchy-alexandria` | 1 | 정답 1위 |

이 측정으로 실제 lexical relevance 결함은 **exact title 문서가 같은 단어를 본문에서 자주 사용하는 문서에 밀릴 수 있는 문제**로 좁혀졌다.

### 6.3 exact-title lexical ranking 계약

PostgreSQL Obsidian FTS는 기존 `ts_rank_cd`에 case-insensitive exact-title 일치 signal을 같은 SQL statement 안에서 가산한다.

```text
chunk ts_rank_cd
+ note ts_rank_cd * 0.5
+ exact normalized title match boost
```

새 SQL round-trip은 추가하지 않는다. focused PostgreSQL regression은 exact-title note가 동일 query phrase를 본문에 반복하는 Daily Health note보다 먼저 반환되는 것을 고정한다.

메인 8000 process는 재시작하지 않고 동일 Docker network와 같은 Vault/PostgreSQL을 사용하는 one-off current-source server에서 재측정했다. exact-title 보정과 아래 first-nonempty fallback 정책을 함께 적용한 결과는 다음과 같다.

```text
Recall@1 = 1.00
Recall@3 = 1.00
MRR      = 1.00
ranking instability = 0
```

### 6.4 Lexical fallback latency 개선

기존 `_search_fts_sources`는 원문 query가 이미 결과를 반환해도 요청 `limit`을 채우기 위해 더 짧고 넓은 query variant를 계속 실행했다. `limit`은 최대 반환 수이지 반드시 채워야 하는 목표가 아니며, query variant는 planner contract상 lexical **fallback**이다.

동일 live backend에서 정책 변경 전 `limit=1`과 `limit=5`를 비교하면 variant expansion 비용이 분리된다.

| Query | limit=1 | limit=5 |
| --- | ---: | ---: |
| Alexandria Memory Steward Contract | 1.28 s | 7.05 s |
| Neo4j 기능 05 Graph-aware Context Retrieval | 1.21 s | 13.35 s |
| Engineering Modernization Contract | 1.04 s | 2.87 s |

정책은 다음처럼 변경한다.

```text
original query
→ non-empty: 그 ranking을 반환하고 종료
→ empty: 다음 focused variant를 시도
→ first non-empty fallback을 반환
→ 모든 variant가 empty: empty result
```

한국어 focused fallback이 보존되는지 별도 unit contract로 고정한다.

변경 후 current-source server에서 4개 project-scoped Golden Query를 warmup 1회 + measured 3회로 재측정한 FTS 결과는 다음과 같다.

| Query | p50 | p95 | Recall@1 | 결과 수 |
| --- | ---: | ---: | ---: | ---: |
| Engineering Modernization Contract | 1.073 s | 1.077 s | 1.00 | 1 |
| Neo4j 기능 05 Graph-aware Context Retrieval | 1.236 s | 1.257 s | 1.00 | 1 |
| Alexandria Memory Steward Contract | 1.308 s | 1.309 s | 1.00 | 1 |
| heterarchy-alexandria Project Index (pre-rebrand measurement) | 1.423 s | 1.463 s | 1.00 | 1 |

정책 변경은 정확한 원문 결과가 있을 때 관련성이 낮은 fallback 결과로 응답을 억지로 채우지 않는다. 더 넓은 recall이 필요한 자연어 질문은 원문 결과가 0건일 때 기존 focused fallback을 그대로 사용한다.

### 6.5 PostgreSQL FTS execution-plan 개선

first-nonempty 정책 후에도 단일 query가 약 1.1~1.4초 걸렸다. PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)`에서 기존 predicate가 다음 형태라 서로 다른 테이블의 두 GIN expression index를 함께 사용하지 못하는 것이 확인됐다.

```text
chunk_document @@ query
OR note_document @@ query
```

대표 `Alexandria Memory Steward Contract` query의 변경 전 plan은 `obsidian_chunks` 14,215행 Seq Scan을 수행했고 execution time은 약 2,121ms였다.

후보 생성을 다음 두 indexed lane의 `UNION`으로 바꿨다.

```text
chunk GIN candidate ids
UNION
note GIN candidate ids → note_id index로 chunk ids 확장
→ candidate ids만 hydrate/rank/filter
```

동일 SQL 의미의 사전 `EXPLAIN ANALYZE`에서 두 GIN index가 모두 사용됐고 execution time은 약 **125ms**로 감소했다. 별도 FTS index나 denormalized canonical data는 추가하지 않았다.

current-source one-off server에서 같은 4개 Golden Query를 warmup 1회 + measured 3회로 다시 실행한 end-to-end 결과는 다음과 같다.

| Query | UNION 전 p50 | UNION 후 p50 | Recall@1 |
| --- | ---: | ---: | ---: |
| Engineering Modernization Contract | 1.073 s | 0.230 s | 1.00 |
| Neo4j 기능 05 Graph-aware Context Retrieval | 1.236 s | 0.219 s | 1.00 |
| Alexandria Memory Steward Contract | 1.308 s | 0.301 s | 1.00 |
| heterarchy-alexandria Project Index (pre-rebrand measurement) | 1.423 s | 0.434 s | 1.00 |

최초 올바른 project-scoped 기준선과 비교해도 품질은 `Recall@1 0.75 → 1.00`으로 개선됐고, query별 수 초에서 10초 이상이던 FTS 응답은 수백 ms 범위로 내려왔다.

### 6.6 Vector / Hybrid 재측정 조건과 최종 health

Vault가 변경되면서 embedding fingerprint status가 다시 `REINDEX_REQUIRED`가 될 수 있다. 이 상태에서는 `VECTOR_ONLY`/`HYBRID` 결과를 정상 품질 기준선으로 기록하지 않는다.

```text
RAG status
→ embedding = HEALTHY
→ stale_rows = 0
→ missing_rows = 0
```

위 조건을 만족한 뒤에만 Vector와 Hybrid Golden Query 측정을 수행한다.

최종 측정 시 Obsidian embedding은 다음 상태였다.

```text
total_rows   = 12965
current_rows = 12965
stale_rows   = 0
missing_rows = 0
embedding    = HEALTHY
default      = HYBRID
```

### 6.7 Vector cold-init과 RAG health hot-path 개선

Vector latency를 phase별로 분리한 결과 pgvector SQL 자체는 대표 query에서 약 18ms였고, FastEmbed provider는 첫 query가 약 1.30초인 반면 동일 model instance의 warm query inference는 p50 약 14.7ms였다.

기존 `MemoryContainer.embedding_provider`가 `providers.Factory`였기 때문에 request-scoped `ContextService` 생성마다 새 FastEmbed provider가 만들어져 ONNX model cold-init을 반복했다. embedding provider는 DB session이나 request state를 보유하지 않는 process-scoped model resource이므로 `providers.Singleton`으로 변경하고, 첫 concurrent lazy initialization만 lock으로 보호했다. 실제 inference 호출은 lock 밖에서 실행한다.

Singleton 적용 전후 `VECTOR_ONLY` current-source Golden Query p50은 약 1.31~1.34초에서 약 0.22초로 감소했다. 이후 검색 hot path의 health 비용을 분리했을 때 다음 비용이 확인됐다.

```text
Context Vault index-status probe       ≈   0.4 ms
Obsidian index-status probe            ≈  39.8 ms
Obsidian detailed source diagnostics   ≈ 128.6 ms
```

검색 request는 vector 사용 가능 여부만 필요하지만 기존 `health_with_index_status()`는 `/rag/status`용 total/current/stale/missing row counts와 stored fingerprint diagnostics까지 매번 계산했다. 이를 다음처럼 분리했다.

```text
search hot path
→ recall_health()
→ lightweight stale-existence/index-status probe만 수행

/rag/status
→ health_with_index_status()
→ 기존 detailed source diagnostics 유지
```

`FTS_ONLY`는 vector dependency를 사용하지 않으므로 embedding index-status probe 자체를 생략한다. Vector/Hybrid에서는 stale embedding을 즉시 감지하는 fail-closed probe를 유지한다.

### 6.8 최종 current-source Golden Query 기준선

모든 최적화를 적용한 current-source one-off server에서 같은 실제 Vault/PostgreSQL와 Rust graph compute를 사용해 warmup 1회 + measured 3회로 `FTS_ONLY`, `VECTOR_ONLY`, `HYBRID`를 측정했다. 모든 전략에서 `Recall@1 = 1.00`, `Recall@3 = 1.00`, `MRR = 1.00`, ranking instability `0`을 유지했다.

| Query | FTS p50 | Vector p50 | Hybrid p50 |
| --- | ---: | ---: | ---: |
| Engineering Modernization Contract | 76 ms | 94 ms | 160 ms |
| Neo4j 기능 05 Graph-aware Context Retrieval | 64 ms | 100 ms | 156 ms |
| Alexandria Memory Steward Contract | 150 ms | 92 ms | 236 ms |
| heterarchy-alexandria Project Index (pre-rebrand measurement) | 285 ms | 93 ms | 379 ms |

최종 범위는 다음과 같다.

```text
FTS_ONLY    p50 ≈  64~285 ms
VECTOR_ONLY p50 ≈  92~100 ms
HYBRID      p50 ≈ 156~379 ms
```

품질 저하 없이 확인된 주요 원인은 다음 세 가지였다.

1. lexical fallback을 limit 충전용으로 반복 실행하던 정책
2. 서로 다른 chunk/note FTS GIN lane을 OR로 묶어 Seq Scan을 유발하던 SQL plan
3. request마다 FastEmbed model cold-init과 상세 embedding diagnostics를 반복하던 DI/health lifetime

Hybrid의 FTS lane과 Vector lane은 현재 같은 request-scoped `AsyncSession` 계열을 공유하므로 단순 `gather` 병렬화는 SQLAlchemy session concurrency 계약을 깨뜨릴 수 있다. 별도 session/lane ownership 설계 없이 latency만을 위해 병렬화하지 않는다.

### 6.9 자연어 semantic corpus와 Hybrid fusion 보정

제목 echo만으로는 실제 장기기억 회수 품질을 판단할 수 없으므로 두 corpus를 별도로 버전 관리한다.

```text
benchmarks/golden_cases.exact_title.v1.json
→ 4개 canonical note exact-title regression

benchmarks/golden_cases.semantic.v1.json
→ 10개 policy/reason/action paraphrase query
```

semantic corpus는 query 문자열이 expected title과 같지 않도록 고정한다. 같은 사실에 대해 둘 이상의 canonical 문서가 직접 정답이 될 수 있으면 accepted title을 복수로 기록한다. 예를 들어 CURRENT Memory Compact lifecycle과 temporal `week_N` 규칙은 `Alexandria Memory Steward Contract`와 `Memory Compact 품질 및 생명주기 Specification`을 모두 정답으로 인정한다.

최초 semantic 측정에서 Vector lane은 강했지만 additive RRF Hybrid가 lexical noise를 과도하게 보상하는 문제가 확인됐다. ground truth 보정 및 최소 semantic tie-bias 적용 상태의 측정은 다음과 같았다.

| Strategy | Recall@1 | Recall@3 | MRR |
| --- | ---: | ---: | ---: |
| FTS_ONLY | 0.40 | 0.40 | 0.40 |
| VECTOR_ONLY | 1.00 | 1.00 | 1.00 |
| HYBRID additive RRF | 0.80 | 1.00 | 0.883 |

실패 케이스를 보면 정답은 Vector에서 1위였지만 일반적인 Daily Compact·review/index 문서가 FTS와 Vector 양쪽에 동시에 나타났다는 이유만으로 reciprocal-rank contribution을 두 번 합산해 정답을 밀어냈다. 두 lane은 독립 corpus가 아니라 같은 canonical content를 서로 다른 방식으로 검색하므로 이 합산은 correlated evidence를 double-count할 수 있다.

Hybrid 내부와 동일한 lane별 candidate limit 30으로 다시 시뮬레이션한 결과, additive RRF는 vector weight를 2.5까지 올려도 semantic Recall@1이 0.80에서 개선되지 않았다. 반면 lane contribution의 `max` 또는 lane-normalized average는 1.01 semantic tie-bias와 함께 semantic 10/10을 모두 1위로 복구했고 exact-title 4/4도 유지했다.

최종 구현은 **best-lane reciprocal-rank fusion**을 선택한다.

```text
FTS reciprocal-rank contribution
Vector reciprocal-rank contribution × 1.01
→ 같은 Context가 여러 lane에 있어도 contribution을 합산하지 않음
→ ranking score는 strongest lane contribution 사용
→ fts_score / vector_score는 둘 다 보존
```

`max`를 선택한 이유는 추가로 관찰된 약한 lane evidence가 기존 강한 evidence의 순위를 낮추지 않는 monotonic 성질을 유지하면서 correlated-lane double-counting을 제거하기 때문이다. 1.01은 raw vector score를 ranking에 직접 섞는 가중치가 아니라 동일 reciprocal rank의 deterministic semantic tie-breaker다.

최종 current-source 실측은 다음과 같다.

| Corpus / Strategy | Recall@1 | Recall@3 | MRR | p50 범위 |
| --- | ---: | ---: | ---: | ---: |
| exact-title / FTS | 1.00 | 1.00 | 1.00 | 61~282 ms |
| exact-title / Vector | 1.00 | 1.00 | 1.00 | 92~103 ms |
| exact-title / Hybrid | 1.00 | 1.00 | 1.00 | 157~368 ms |
| semantic / FTS | 0.40 | 0.40 | 0.40 | 17~621 ms |
| semantic / Vector | 1.00 | 1.00 | 1.00 | 103~116 ms |
| semantic / Hybrid | 1.00 | 1.00 | 1.00 | 120~723 ms |

모든 Vector/Hybrid semantic case에서 repeated ranking instability는 0이었다. semantic Hybrid의 latency 상단은 FTS fallback 비용과 shared request-scoped SQLAlchemy session 때문에 두 lane을 순차 실행하는 현재 구조의 영향을 받는다. correctness를 희생하거나 같은 session에 `gather`를 적용해 concurrency contract를 깨면서 줄이지 않는다.

### 6.10 MCP v2 local shell probe

별도 shell benchmark는 GPT connector의 OAuth session을 자동 공유하지 않는다. bearer token이 없는 경우 transport 생성 후 `initialize`가 거절되는 것이 정상이며, 이 결과를 GPT MCP 연결 실패로 해석하지 않는다.

## 7. 다음 최적화 순서

현재 evidence 기준 우선순위는 다음과 같다.

1. semantic corpus를 10개에서 더 다양한 한글·영문·혼합어·짧은 query·identifier query로 확대해 best-lane fusion의 일반화를 검증
2. semantic FTS fallback이 필요한 query와 불필요한 query를 구분할 수 있는 planner evidence를 수집하고, 필요할 때만 query-type routing을 검토
3. Graph evidence가 실제 multi-hop recall을 개선하는 별도 corpus를 만들고 latency 대비 효과를 정량화
4. Hybrid lane 병렬화는 독립 session ownership을 설계할 명확한 latency 필요가 생길 때만 검토
5. Vault 규모가 크게 증가해 pgvector exact scan 비용이 의미 있게 커질 때만 HNSW/IVFFlat 도입 여부를 `EXPLAIN ANALYZE` 근거로 재평가

절대 latency는 CI threshold로 사용하지 않는다. 검색 품질도 현재 데이터셋 숫자를 영구 상수로 고정하지 않고, 버전 관리된 Golden Query contract와 동일 환경의 before/after 비교로 판단한다.
