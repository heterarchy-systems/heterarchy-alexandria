# Troubleshooting Guide 01 — symptom-based checks

## 목적

설치/기능 문제가 생겼을 때 증상별로 확인한다.

## Backend health 실패

### 증상

```text
connection refused
HTTP 5xx
health not ok
```

### 확인

```bash
heterarchy-alexandria --base-url http://localhost:8000 --json health
curl http://localhost:8000/health/ready
```

### 조치

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Context recall 결과 없음

### 확인

```bash
heterarchy-alexandria context recall "your query" --strategy FTS_ONLY --limit 5
heterarchy-alexandria context recall "your query" --strategy FTS_ONLY --project <project> --limit 5
```

### 조치

- project/kind filter를 잠시 제거한다.
- 저장한 context title/content에 query 단어가 있는지 확인한다.
- `/contexts`에서 archive 상태인지 확인한다.

## Vector/RAG degraded

### 확인

```bash
heterarchy-alexandria context doctor-rag
```

### 조치

- smoke test는 `FTS_ONLY`로 먼저 통과시킨다.
- vector를 쓰려면 backend config의 FastEmbed/sqlite-vec 설정을 확인한다.
- migration 후 backend를 재시작한다.

## MCP snippet은 있는데 Hermes tool이 안 보임

### 원인

`~/.hermes/heterarchy-alexandria/mcp-config.json`은 snippet이다. 실제 Hermes runtime은 `~/.hermes/config.yaml`의 `mcp_servers.alexandria`를 읽는다.

### 확인

```bash
hermes mcp list
hermes mcp test alexandria
```

### 조치

```bash
ALEXANDRIA_CLI="$(command -v heterarchy-alexandria)"
hermes mcp add alexandria \
  --command "$ALEXANDRIA_CLI" \
  --args mcp serve \
  --env ALEXANDRIA_API_URL="http://localhost:8000" \
  --env ALEXANDRIA_OPERATOR_API_KEY="${ALEXANDRIA_OPERATOR_API_KEY:-}" \
  --env HERMES_HOME="$HOME/.hermes"
```

그 뒤 Hermes CLI/Gateway/Discord 세션을 재시작한다.

## 제거된 frontend 명령이 아직 실행됨

### 증상

```text
.next scandir, npm, 또는 frontend workflow 관련 정적 검사/테스트가 실패한다.
```

### 조치

현재 런타임은 backend/CLI/MCP만 남아 있다. stale script나 CI step에서 frontend 명령을 제거하고 backend 검증을 실행한다.

```bash
cd backend
uv run ruff check .
uv run pyrefly check
uv run pytest -q
```

## Protected route가 401

### 증상

```text
Operator API key required
```

### 확인/조치

- backend `.env`의 `ALEXANDRIA_OPERATOR_API_KEY`와 client/MCP env의 `ALEXANDRIA_OPERATOR_API_KEY`가 같은지 확인한다.
- 실제 값은 로그/문서에 출력하지 않는다.
- 일반 context/library read-only smoke test는 operator key 없이도 가능한 경로가 있다.
