# Install/Onboard Guide 01 — 처음 설치 후 Hermes에 Alexandria 붙이기

## 목적

처음 사용하는 사람이 heterarchy-alexandria를 설치한 뒤 Hermes가 로컬/현재 컨텍스트를 먼저 쓰고, 부족할 때 Alexandria를 자연스럽게 사용할 수 있게 만든다.

heterarchy-alexandria는 **로그인 없는 single-operator/local-first** 시스템이다.
기본 온보딩에는 GPT/Codex OAuth나 provider credential이 필요하지 않으며,
`ALEXANDRIA_OPERATOR_API_KEY` 하나가 보호된 MCP local-approval과 vault
maintenance control-plane 작업을 보호한다.

## 전제

- heterarchy-alexandria backend가 실행 가능하다.
- `heterarchy-alexandria` CLI가 PATH에 있다.
- Hermes Agent가 설치되어 있다.
- operator key가 필요한 기능은 실제 secret을 문서에 남기지 않는다.
- Docker/로컬 기본값은 localhost/private operator 사용을 전제로 한다. 외부 노출 전에는 VPN,
  reverse proxy auth, firewall allowlist, SSH tunnel 중 하나 이상의 access boundary를 둔다.

## 빠른 흐름

```bash
set -a
[ -f .env ] && . ./.env
set +a

export ALEXANDRIA_API_URL="${ALEXANDRIA_API_URL:-http://localhost:8000}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export ALEXANDRIA_OPERATOR_API_KEY="${ALEXANDRIA_OPERATOR_API_KEY:-}"

curl -fsS "$ALEXANDRIA_API_URL/health/live"
curl -fsS "$ALEXANDRIA_API_URL/operations/readiness" | jq
heterarchy-alexandria memory-steward check --project heterarchy-alexandria
```

## 확인

```bash
heterarchy-alexandria mcp smoke-tools --mcp-url "$ALEXANDRIA_API_URL/mcp/"
```

성공 기준:

- `/health/live` returns `{"status":"ok"}`
- `/operations/readiness` reports the current PostgreSQL/vault/RAG state
- `memory-steward check` completes with an actionable result

## Runtime 사용 계약

설치 성공은 “OAuth 연결”이나 “MCP discovery”에서 끝나지 않는다. Hermes가 실제 작업에 들어갈 때 아래 계약을 따라야 한다.

1. 현재 대화, Hermes local memory, loaded/local/built-in skill을 먼저 사용한다.
2. 충분하면 Alexandria를 호출하지 않는다.
3. 부족하거나 이전 작업을 이어가거나 durable/shared context가 필요하면 current Memory Compact를 먼저 읽는다.
4. 그래도 빈틈이 있으면 Context Vault recall/RAG로 필요한 결정/핸드오프/버그 원인/compact detail만 좁게 찾는다.
5. START_HERE는 unfamiliar agent가 로컬 맥락이 부족할 때 보는 도서관 입구다.
6. Memory Compact와 reconciliation은 Memory Steward boundary를 사용한다.

## Hermes MCP runtime 등록

`~/.hermes/heterarchy-alexandria/mcp-config.json`은 snippet이다. 실제 Hermes tool discovery는 `~/.hermes/config.yaml`의 `mcp_servers` 등록을 봐야 한다.

```bash
ALEXANDRIA_CLI="$(command -v heterarchy-alexandria)"
hermes mcp add alexandria   --command "$ALEXANDRIA_CLI"   --args mcp serve   --env ALEXANDRIA_API_URL="$ALEXANDRIA_API_URL"   --env ALEXANDRIA_OPERATOR_API_KEY="${ALEXANDRIA_OPERATOR_API_KEY:-}"   --env HERMES_HOME="$HERMES_HOME"

hermes mcp test alexandria
```

설정 후 Hermes CLI/Gateway/Discord 세션을 재시작한다.

## 흔한 오해

- `mcp-config.json`만 있으면 Hermes가 tool을 자동 발견한다고 생각하면 안 된다.
- operator key는 OAuth token이 아니다. MCP local-approval과 protected maintenance route에만 사용한다.
- Alexandria는 local memory 대체물이 아니다. local-first, Alexandria-when-needed가 기본 계약이다.
- 장기기억 조회는 Memory Steward와 Context Vault MCP boundary를 사용한다.

MCP client OAuth가 필요하면 `/connect`의 local MCP client 관리와 pairing-code
흐름을 사용한다. provider delegation이나 외부 Librarian 설정은 현재 제품 표면에
포함되지 않는다.
